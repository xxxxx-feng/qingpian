"""Image decoding, conservative tone adjustment, and non-overwriting exports.

No GUI or network access is needed by this module. All processing is local.
"""

from __future__ import annotations

import io
import math
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageCms, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".heic", ".heif"})
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
SRGB_BYTES = SRGB_PROFILE.tobytes()
LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


class ProcessingCancelled(Exception):
    """Raised between processing tiles when cancellation is requested."""


@dataclass(frozen=True)
class Adjustments:
    # A conservative portrait-oriented starting point, not an industry standard.
    # Phone JPEG/HEIC white balance is already baked in; keep it neutral.
    auto: float = 0.75
    exposure: float = 0.0
    shadows: float = 0.35
    highlights: float = 0.60
    contrast: float = 0.02
    temperature: float = 0.0
    vibrance: float = 0.08
    intensity: float = 1.0
    adaptive: bool = False

    def __post_init__(self):
        limits = {
            "auto": (0, 1), "exposure": (-1, 1.5), "shadows": (0, 1),
            "highlights": (0, 1), "contrast": (-0.3, 0.3),
            "temperature": (-1, 1), "vibrance": (-0.5, 0.6),
            "intensity": (0, 1),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"无效参数 {name}: {value}")


DEFAULT_PRESET = "全自动自然"
STUDIO_PRESET = "影楼自然光"

PRESETS = {
    DEFAULT_PRESET: Adjustments(adaptive=True),
    STUDIO_PRESET: Adjustments(),
    "自然提亮": Adjustments(auto=0.70, shadows=0.30, highlights=0.35,
                             contrast=0.03, vibrance=0.15),
    "清透日常": Adjustments(auto=0.8, shadows=0.4, highlights=0.5,
                             contrast=0.06, temperature=-0.06, vibrance=0.22),
    "温暖人像": Adjustments(auto=0.6, shadows=0.25, highlights=0.45,
                             contrast=0.0, temperature=0.22, vibrance=0.08),
}


@dataclass(frozen=True)
class AutoPlan:
    exposure_ev: float = 0.0
    shadows: float = 0.0
    highlights: float = 0.0
    contrast: float = 0.0
    vibrance: float = 0.0
    white_balance: tuple[float, float, float] = (1.0, 1.0, 1.0)
    white_balance_confidence: float = 0.0
    low_light: bool = False
    backlit: bool = False
    description: str = "保留原有光线"


@dataclass
class Photo:
    image: Image.Image
    exif: bytes
    size: tuple[int, int]
    suggested_ev: float
    warning: str = ""
    auto_plan: AutoPlan | None = None


def check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise ProcessingCancelled()


def collect_photos(paths: list[Path], recursive: bool = False,
                   cancel: threading.Event | None = None, *,
                   source_roots: dict[Path, Path] | None = None) -> list[Path]:
    """Resolve/deduplicate paths; never follow directory symlinks recursively."""
    found: dict[Path, None] = {}
    for given in paths:
        check_cancel(cancel)
        path = Path(given).expanduser()
        if path.is_dir():
            for parent, directories, files in os.walk(path, followlinks=False):
                check_cancel(cancel)
                directories[:] = sorted(d for d in directories if not d.startswith("."))
                for name in sorted(files):
                    candidate = Path(parent) / name
                    if (not name.startswith(".") and not candidate.is_symlink()
                            and candidate.suffix.lower() in SUPPORTED_EXTENSIONS):
                        resolved = candidate.resolve()
                        found[resolved] = None
                        if source_roots is not None:
                            previous = source_roots.get(resolved)
                            root = path.resolve()
                            if previous is None or previous.is_relative_to(root):
                                source_roots[resolved] = root
                if not recursive:
                    break
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            resolved = path.resolve()
            found[resolved] = None
            if source_roots is not None:
                source_roots.setdefault(resolved, resolved.parent)
    return sorted(found, key=lambda p: (p.name.casefold(), str(p)))


def _to_linear(values: np.ndarray) -> np.ndarray:
    return np.where(values <= 0.04045, values / 12.92,
                    ((values + 0.055) / 1.055) ** 2.4)


def _to_srgb(values: np.ndarray) -> np.ndarray:
    values = np.maximum(values, 0)
    return np.where(values <= 0.0031308, values * 12.92,
                    1.055 * values ** (1 / 2.4) - 0.055)


def _p3_to_srgb(image: Image.Image) -> Image.Image:
    # Display P3 uses the sRGB transfer curve and D65 white point.
    matrix = np.array([[1.224745, -0.224904, 0.0],
                       [-0.042058, 1.042081, 0.0],
                       [-0.019642, -0.078655, 1.098537]], dtype=np.float32)
    output = Image.new("RGB", image.size)
    for y in range(0, image.height, 256):
        box = (0, y, image.width, min(y + 256, image.height))
        pixels = np.asarray(image.crop(box), dtype=np.float32) / 255
        converted = _to_srgb(_to_linear(pixels) @ matrix.T)
        output.paste(Image.fromarray(np.uint8(np.clip(converted * 255 + 0.5, 0, 255))), box)
    return output


def suggest_exposure(image: Image.Image) -> float:
    sample = image.copy()
    sample.thumbnail((512, 512), Image.Resampling.LANCZOS)
    pixels = np.asarray(sample, dtype=np.float32) / 255
    luminance = pixels @ LUMA
    # Ignore near-black borders, while leaving genuinely black images untouched.
    visible = luminance[luminance > 0.015]
    if visible.size < max(16, luminance.size * 0.02):
        return 0.0
    midtone = float(np.percentile(visible, 60))
    return float(np.clip(math.log2(0.50 / max(midtone, 0.025)), 0, 1.6))


def _neutral_balance(pixels: np.ndarray, luminance: np.ndarray) -> tuple[tuple, float]:
    """Small corrections only when distributed, similarly tinted neutrals agree.

    This deliberately abstains on strongly colored scenes instead of assuming
    the scene average must be gray. It is not semantic illuminant recognition.
    """
    maximum = pixels.max(axis=2)
    chroma = maximum - pixels.min(axis=2)
    neutral = ((luminance > 0.20) & (luminance < 0.90)
               & (maximum < 0.95) & (chroma < 0.20 * maximum))
    if neutral.mean() < 0.015 or neutral.sum() < 64:
        return (1.0, 1.0, 1.0), 0.0
    neutral_lum = luminance[neutral]
    low, high = np.percentile(neutral_lum, [10, 90])
    if high - low < 0.12:
        return (1.0, 1.0, 1.0), 0.0
    normalized = pixels / np.maximum(luminance[..., None], 1e-5)
    cells = []
    height, width = luminance.shape
    for row in range(4):
        for column in range(4):
            ys = slice(row * height // 4, (row + 1) * height // 4)
            xs = slice(column * width // 4, (column + 1) * width // 4)
            mask = neutral[ys, xs]
            if mask.size and mask.mean() > 0.03 and mask.sum() >= 8:
                cells.append(np.median(normalized[ys, xs][mask], axis=0))
    if len(cells) < 4:
        return (1.0, 1.0, 1.0), 0.0
    cells = np.asarray(cells)
    agreement = float(np.max(np.std(cells, axis=0)))
    midpoint = float(np.median(neutral_lum))
    dim_mask = neutral & (luminance <= midpoint)
    bright_mask = neutral & (luminance > midpoint)
    if not dim_mask.any() or not bright_mask.any():
        return (1.0, 1.0, 1.0), 0.0
    dim = np.median(normalized[dim_mask], axis=0)
    bright = np.median(normalized[bright_mask], axis=0)
    if not np.all(np.isfinite(bright)) or np.max(np.abs(dim - bright)) > 0.045 or agreement > 0.04:
        return (1.0, 1.0, 1.0), 0.0
    confidence = float(np.clip((1 - agreement / 0.06) * min(1, neutral.mean() / 0.20), 0, 1))
    channels = np.median(cells, axis=0)
    gray = float(np.exp(np.log(channels).mean()))
    gains = np.clip((gray / channels) ** (0.45 * confidence), 0.94, 1.06)
    gains /= float(gains @ LUMA)
    return tuple(float(value) for value in gains), confidence


def analyze_photo(image: Image.Image) -> AutoPlan:
    """Create one deterministic, bounded plan from the color-managed original.

    The same plan is stored before preview downsampling and reused in export.
    Scene labels describe histogram/spatial heuristics, not AI recognition.
    """
    sample = image.copy()
    sample.thumbnail((768, 768), Image.Resampling.LANCZOS)
    pixels = np.asarray(sample, dtype=np.float32) / 255
    lum = pixels @ LUMA
    visible = lum[lum > 0.015]
    if visible.size < max(16, lum.size * 0.02):
        return AutoPlan(low_light=True, description="保留暗光氛围")
    p10, p25, p50, p55, p75, p90, p95 = np.percentile(visible, [10, 25, 50, 55, 75, 90, 95])
    if p10 > 0.995:
        return AutoPlan(description="保留明亮画面")
    height, width = lum.shape
    center = lum[height // 5:max(height // 5 + 1, height * 4 // 5),
                 width // 5:max(width // 5 + 1, width * 4 // 5)]
    center_median = float(np.median(center))
    low_light = bool(p75 < 0.18 or (np.median(lum) < 0.09 and np.mean(lum < 0.12) > 0.70))
    backlit = bool(not low_light and p95 > 0.73 and center_median < 0.38
                   and p90 - p25 > 0.38)
    metered = max(0.02, 0.55 * float(np.percentile(lum, 55) if low_light else p55) + 0.45 * center_median)
    if backlit:
        # Bright windows/sky must not make a shadowed central subject darker.
        metered = max(0.02, 0.15 * float(p55) + 0.85 * center_median)
    target = 0.24 if low_light else 0.46
    linear_target = float(_to_linear(np.array(target)))
    linear_meter = float(_to_linear(np.array(metered)))
    exposure = math.log2((linear_target + 0.02) / (linear_meter + 0.02)) * 0.65
    exposure = float(np.clip(exposure, -0.35, 0.55 if low_light else 0.75 if backlit else 1.15))
    if 0.42 <= metered <= 0.60:
        exposure = 0.0
    shadows = float(np.clip((0.36 - p25) / 0.32, 0, 1) * 0.55)
    if backlit:
        shadows = max(shadows, 0.35)
    if low_light:
        shadows = min(shadows, 0.18)
    highlights = float(np.clip((p95 - 0.62) / 0.36, 0, 1) * 0.85)
    contrast = float(np.clip((0.50 - (p90 - p10)) * 0.14, -0.035, 0.065))
    if low_light:
        contrast = 0.0
    maximum, minimum = pixels.max(axis=2), pixels.min(axis=2)
    saturation = (maximum - minimum) / np.maximum(maximum, 1e-5)
    color_sample = saturation[(lum > 0.10) & (lum < 0.85)]
    typical_saturation = float(np.percentile(color_sample, 65)) if color_sample.size else 0.0
    vibrance = float(np.clip((0.38 - typical_saturation) * 0.28, -0.045, 0.10))
    if low_light:
        vibrance = min(vibrance, 0.025)
    balance, confidence = _neutral_balance(pixels, lum) if not low_light else ((1.0, 1.0, 1.0), 0.0)
    if low_light:
        descriptions = ["暗光轻调"]
    elif backlit:
        descriptions = ["逆光提亮"]
    elif exposure > 0.05:
        descriptions = ["柔和提亮"]
    elif exposure < -0.05:
        descriptions = ["明亮平衡"]
    else:
        descriptions = ["保留原有亮度"]
    if highlights > 0.4:
        descriptions.append("高光保护")
    if max(abs(value - 1) for value in balance) > 0.012:
        descriptions.append("轻调偏色")
    elif vibrance > 0.04:
        descriptions.append("自然增色")
    return AutoPlan(exposure, shadows, highlights, contrast, vibrance, balance,
                    confidence, low_light, backlit, " · ".join(descriptions[:3]))


def load_photo(path: Path, preview_edge: int | None = None) -> Photo:
    """Normalize orientation and color space before previewing or editing."""
    with Image.open(path) as source:
        source.load()
        info = source.info.copy()
        oriented = ImageOps.exif_transpose(source)
        exif = oriented.getexif()
        # Do not copy opaque maker notes/embedded thumbnails from another image.
        safe_exif = Image.Exif()
        for tag in (271, 272, 305, 306, 315, 33432):
            if tag in exif:
                safe_exif[tag] = exif[tag]
        for ifd_id in (34665, 34853):  # EXIF camera/date fields and GPS
            if ifd_id in exif:
                fields = dict(exif.get_ifd(ifd_id))
                if ifd_id == 34665:
                    fields.pop(37500, None)  # maker-note offsets are not relocatable
                    fields.pop(40965, None)  # interoperability IFD
                    fields[40961] = 1        # sRGB
                    fields[40962], fields[40963] = oriented.size
                safe_exif[ifd_id] = fields
        size = oriented.size
        image = oriented.convert("RGB")
        warning = ""
        icc = info.get("icc_profile")
        if icc:
            try:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                image = ImageCms.profileToProfile(image, profile, SRGB_PROFILE, outputMode="RGB")
            except (ImageCms.PyCMSError, OSError, ValueError) as exc:
                raise ValueError("照片的色彩配置损坏，无法可靠转换颜色") from exc
        else:
            nclx = info.get("nclx_profile") or {}
            primaries = nclx.get("color_primaries", 1)
            transfer = nclx.get("transfer_characteristics", 13)
            if transfer in (16, 18):
                raise ValueError("此 HEIC 使用 HDR/PQ 或 HLG，请先从相册导出为 SDR JPG")
            if primaries == 12 and transfer in (1, 13):
                if transfer != 13:
                    raise ValueError("此 HEIC 的 P3 传递曲线暂不支持，请先导出为 JPG")
                image = _p3_to_srgb(image)
            elif primaries not in (1, 2):
                raise ValueError("此 HEIC 的色彩空间暂不支持，请先从相册导出为 JPG")
        suggested_ev = suggest_exposure(image)
        auto_plan = analyze_photo(image)
        if preview_edge:
            image.thumbnail((preview_edge, preview_edge), Image.Resampling.LANCZOS)
        return Photo(image, safe_exif.tobytes(), size, suggested_ev, warning, auto_plan)


def adjust_photo(photo: Photo, settings: Adjustments,
                 cancel: threading.Event | None = None) -> Image.Image:
    """Process in tiles, so 48 MP photos do not require huge float buffers."""
    check_cancel(cancel)
    if settings.intensity == 0:
        return photo.image.copy()
    image = photo.image
    output = Image.new("RGB", image.size)
    if settings.adaptive:
        plan = photo.auto_plan or analyze_photo(image)
        gain = 2 ** plan.exposure_ev
        warmth = np.array(plan.white_balance, dtype=np.float32)
        shadows, highlights = plan.shadows, plan.highlights
        contrast, vibrance = plan.contrast, plan.vibrance
    else:
        gain = 2 ** (photo.suggested_ev * settings.auto + settings.exposure)
        warmth = np.array([2 ** (settings.temperature * 0.14), 1,
                           2 ** (-settings.temperature * 0.14)], dtype=np.float32)
        shadows, highlights = settings.shadows, settings.highlights
        contrast, vibrance = settings.contrast, settings.vibrance
    for y in range(0, image.height, 192):
        check_cancel(cancel)
        box = (0, y, image.width, min(y + 192, image.height))
        original = np.asarray(image.crop(box), dtype=np.float32) / 255
        linear = _to_linear(original)
        if gain >= 1:
            # Apply a common luminance gain to all channels to preserve hue.
            lum = (linear @ LUMA)[..., None]
            linear *= gain / (1 + lum * (gain - 1))
        else:
            linear *= gain
        pixels = _to_srgb(linear) * warmth
        lum = (pixels @ LUMA)[..., None]
        target = lum + shadows * 0.24 * (1 - lum) ** 2 * (1 - np.exp(-12 * lum))
        target -= highlights * 0.16 * lum ** 3 * (1 - lum)
        target = target + contrast * (target - 0.5) * 4 * target * (1 - target)
        pixels *= target / np.maximum(lum, 1e-6)
        lum = (pixels @ LUMA)[..., None]
        saturation = (pixels.max(axis=2) - pixels.min(axis=2))[..., None]
        color_strength = vibrance * (1 - np.clip(saturation, 0, 1))
        if settings.adaptive and vibrance > 0:
            # Reduce extra saturation in warm hues; this is color-based, not
            # face detection, and includes similarly colored objects as well.
            warm = ((pixels[..., 0] > pixels[..., 1])
                    & (pixels[..., 1] > pixels[..., 2]))[..., None]
            color_strength *= np.where(warm, 0.35, 1.0)
        factor = 1 + color_strength
        pixels = lum + (pixels - lum) * factor
        # Compress out-of-gamut color toward gray rather than clipping channels.
        delta = pixels - lum
        room = np.where(delta > 0, (1 - lum) / np.maximum(delta, 1e-6),
                        lum / np.maximum(-delta, 1e-6))
        scale = np.minimum(1, np.maximum(0, room.min(axis=2, keepdims=True)))
        pixels = lum + delta * scale
        pixels = original + (pixels - original) * settings.intensity
        output.paste(Image.fromarray(np.uint8(np.clip(pixels * 255 + 0.5, 0, 255))), box)
    check_cancel(cancel)
    return output


def source_created_at(path: Path) -> datetime:
    """Original file creation time in the computer's local timezone.

    Unix st_ctime is metadata-change time, so it must never be used as a
    substitute for creation time on platforms that lack st_birthtime.
    """
    stat = Path(path).stat()
    timestamp = getattr(stat, "st_birthtime", None)
    if timestamp is None and sys.platform == "win32":
        timestamp = stat.st_ctime  # Python < 3.12 Windows compatibility.
    if timestamp is None or not math.isfinite(timestamp):
        raise ValueError("无法读取原照片的文件创建时间；请在支持创建时间的 Mac 或 Windows 文件系统上导出")
    return datetime.fromtimestamp(timestamp)


def _export_directories(paths: list[Path], output_dir: Path,
                        source_roots: dict[Path, Path] | None) -> list[Path]:
    resolved = [Path(path).resolve() for path in paths]
    known = {Path(p).resolve(): Path(root).resolve() for p, root in (source_roots or {}).items()}
    missing = [path for path in resolved if path not in known]
    if missing:
        try:
            common = Path(os.path.commonpath([str(path.parent) for path in missing]))
            known.update({path: common for path in missing})
        except ValueError:  # Windows inputs on different drives.
            known.update({path: Path(path.anchor) for path in missing})
    candidates = set(known.values())
    roots = sorted((root for root in candidates if not any(
        root != other and root.is_relative_to(other) for other in candidates)), key=str)
    aliases, used = {}, set()
    for root in roots:
        base = root.name or root.drive.replace(":", "") or "照片"
        name, serial = base, 2
        while name.casefold() in used:
            name = f"{base}_{serial}"
            serial += 1
        used.add(name.casefold())
        aliases[root] = name
    directories = []
    for path in resolved:
        root = next(root for root in roots if path.is_relative_to(root))
        relative = path.parent.relative_to(root)
        prefix = Path(aliases[root]) if len(roots) > 1 else Path()
        directories.append(Path(output_dir) / prefix / relative)
    return directories


def _export_plan(paths: list[Path], output_dir: Path,
                 source_roots: dict[Path, Path] | None,
                 cancel: threading.Event | None) -> list[tuple]:
    directories = _export_directories(paths, output_dir, source_roots)
    planned = [None] * len(paths)
    groups = {}
    for index, (path, directory) in enumerate(zip(paths, directories)):
        check_cancel(cancel)
        try:
            created = source_created_at(path)
            day = created.strftime("%Y-%m-%d")
            groups.setdefault((directory, day), []).append((created, str(path), index))
        except Exception as exc:
            planned[index] = (directory, None, str(exc) or type(exc).__name__)
    for (directory, day), members in groups.items():
        check_cancel(cancel)
        try:
            occupied = {p.name.casefold() for p in directory.iterdir()} if directory.exists() else set()
            serial = None if len(members) == 1 and f"{day}.jpg" not in occupied else 1
            for _, _, index in sorted(members):
                name = f"{day}.jpg" if serial is None else f"{day}_{serial}.jpg"
                while name.casefold() in occupied:
                    serial = 1 if serial is None else serial + 1
                    name = f"{day}_{serial}.jpg"
                planned[index] = (directory, serial, "")
                occupied.add(name.casefold())
                serial = 1 if serial is None else serial + 1
        except Exception as exc:
            for _, _, index in members:
                planned[index] = (directory, None, str(exc) or type(exc).__name__)
    return planned


def export_photo(path: Path, output_dir: Path, settings: Adjustments,
                 quality: int = 95, keep_metadata: bool = True,
                 cancel: threading.Event | None = None, *,
                 sequence: int | None = None) -> Path:
    """Create a date-named JPEG exclusively; never overwrite any file."""
    if not 80 <= quality <= 100:
        raise ValueError("JPEG 品质必须在 80 到 100 之间")
    check_cancel(cancel)
    day = source_created_at(path).strftime("%Y-%m-%d")
    if sequence is not None and sequence < 1:
        raise ValueError("照片序号必须大于零")
    photo = load_photo(path)
    result = adjust_photo(photo, settings, cancel)
    check_cancel(cancel)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    options = dict(format="JPEG", quality=quality, subsampling=0,
                   optimize=True, icc_profile=SRGB_BYTES)
    if keep_metadata:
        options["exif"] = photo.exif
    # Encoding finishes before a destination is created. This also keeps cancel
    # requests during encoding from leaving a partial exported file.
    encoded = io.BytesIO()
    result.save(encoded, **options)
    check_cancel(cancel)
    serial = sequence
    while True:
        suffix = "" if serial is None else f"_{serial}"
        destination = output_dir / f"{day}{suffix}.jpg"
        try:
            handle = destination.open("xb")
        except FileExistsError:
            serial = 1 if serial is None else serial + 1
            continue
        try:
            with handle:
                handle.write(encoded.getbuffer())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return destination


def export_batch(paths: list[Path], output_dir: Path, settings: Adjustments,
                 quality: int = 95, keep_metadata: bool = True,
                 cancel: threading.Event | None = None,
                 progress: Callable | None = None, *,
                 source_roots: dict[Path, Path] | None = None) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Keep imported subdirectories and number each directory/day separately."""
    successes, failures = [], []
    if not paths or (cancel is not None and cancel.is_set()):
        return successes, failures
    try:
        plan = _export_plan(paths, Path(output_dir), source_roots, cancel)
    except ProcessingCancelled:
        return successes, failures
    for index, (path, (directory, sequence, planning_error)) in enumerate(zip(paths, plan)):
        if cancel is not None and cancel.is_set():
            break
        try:
            if planning_error:
                raise ValueError(planning_error)
            destination = export_photo(path, directory, settings, quality, keep_metadata,
                                       cancel, sequence=sequence)
            successes.append(destination)
            error = ""
        except ProcessingCancelled:
            break
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            failures.append((path, error))
        if progress:
            progress(index + 1, len(paths), path, error)
    return successes, failures

