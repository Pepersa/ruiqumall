import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from .product_images import IMAGE_EXTENSIONS, product_image_root, safe_directory


ALLOWED_GALLERY_DIRECTORIES = {'主图透图', '详情页', '详情图'}
IGNORED_ARCHIVE_NAMES = {'.DS_Store'}
MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024
MIN_FREE_SPACE_BYTES = 200 * 1024 * 1024


class ProductImageArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class ProductImageArchiveResult:
    style_codes: tuple[str, ...]
    image_count: int
    uncompressed_bytes: int


def normalized_archive_parts(name):
    normalized = name.replace('\\', '/')
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in path.parts):
        raise ProductImageArchiveError(f'压缩包包含不安全路径：{name}')
    return path.parts


def is_symbolic_link(info):
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def archive_file_entries(archive):
    entries = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = normalized_archive_parts(info.filename)
        if parts[0] == '__MACOSX' or parts[-1] in IGNORED_ARCHIVE_NAMES:
            continue
        if is_symbolic_link(info):
            raise ProductImageArchiveError(f'压缩包不能包含符号链接：{info.filename}')
        if info.flag_bits & 0x1:
            raise ProductImageArchiveError(f'压缩包不能包含加密文件：{info.filename}')
        entries.append((info, parts))
    if not entries:
        raise ProductImageArchiveError('压缩包中没有可导入的图片。')
    return entries


def strip_optional_product_catalog_root(entries):
    if all(parts[0] == 'product_catalog' for _, parts in entries):
        stripped = []
        for info, parts in entries:
            if len(parts) == 1:
                continue
            stripped.append((info, parts[1:]))
        return stripped
    return entries


def validate_archive_entries(entries, known_style_codes):
    known_style_codes = set(known_style_codes)
    validated = []
    seen_paths = set()
    style_codes = set()
    total_bytes = 0

    if len(entries) > MAX_ARCHIVE_FILES:
        raise ProductImageArchiveError(f'压缩包文件数量不能超过 {MAX_ARCHIVE_FILES} 个。')

    for info, parts in entries:
        if len(parts) not in {3, 4}:
            raise ProductImageArchiveError(
                f'目录结构不正确：{info.filename}。'
                '应为“款式编码/主图透图/图片”或“款式编码/详情页/图片”。'
            )
        style_code = parts[0]
        gallery_directory = parts[-2]
        filename = parts[-1]
        if style_code not in known_style_codes:
            raise ProductImageArchiveError(f'款式编码不存在：{style_code}')
        if gallery_directory not in ALLOWED_GALLERY_DIRECTORIES:
            raise ProductImageArchiveError(f'不支持的图片目录：{gallery_directory}')
        if len(parts) == 4 and parts[1] in ALLOWED_GALLERY_DIRECTORIES:
            raise ProductImageArchiveError(f'目录结构不正确：{info.filename}')
        if Path(filename).suffix.casefold() not in IMAGE_EXTENSIONS:
            raise ProductImageArchiveError(f'文件不是支持的图片格式：{info.filename}')
        destination = PurePosixPath(*parts).as_posix()
        if destination in seen_paths:
            raise ProductImageArchiveError(f'压缩包包含重复文件路径：{destination}')
        seen_paths.add(destination)
        style_codes.add(style_code)
        total_bytes += info.file_size
        if total_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ProductImageArchiveError('压缩包解压后的总大小不能超过 10 GB。')
        validated.append((info, parts))

    return validated, style_codes, total_bytes


def extract_validated_entries(archive, entries, staging_root):
    for info, parts in entries:
        destination = safe_directory(staging_root, *parts)
        if not destination:
            raise ProductImageArchiveError(f'压缩包包含不安全路径：{info.filename}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, destination.open('xb') as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


def rollback_replacements(replacements, discard_root):
    for style_code, target, backup in reversed(replacements):
        if target.exists():
            discard = discard_root / style_code
            discard.parent.mkdir(parents=True, exist_ok=True)
            target.rename(discard)
        if backup and backup.exists():
            backup.rename(target)


def replace_style_directories(staging_root, image_root, style_codes, work_root):
    backups_root = work_root / 'backups'
    discard_root = work_root / 'discard'
    backups_root.mkdir()
    discard_root.mkdir()
    replacements = []

    try:
        for style_code in sorted(style_codes):
            source = safe_directory(staging_root, style_code)
            target = safe_directory(image_root, style_code)
            if not source or not source.is_dir() or not target:
                raise ProductImageArchiveError(f'无法准备款式目录：{style_code}')

            backup = None
            if target.exists():
                if not target.is_dir():
                    raise ProductImageArchiveError(f'目标不是目录，无法覆盖：{style_code}')
                backup = backups_root / style_code
                target.rename(backup)
            try:
                source.rename(target)
            except Exception:
                if backup and backup.exists():
                    backup.rename(target)
                raise
            replacements.append((style_code, target, backup))
    except Exception:
        rollback_replacements(replacements, discard_root)
        raise


def import_product_image_archive(uploaded_file, *, known_style_codes, image_root=None):
    image_root = Path(image_root or product_image_root()).resolve()
    image_root.parent.mkdir(parents=True, exist_ok=True)
    image_root.mkdir(parents=True, exist_ok=True)

    try:
        uploaded_file.seek(0)
        with ZipFile(uploaded_file) as archive:
            entries = strip_optional_product_catalog_root(archive_file_entries(archive))
            entries, style_codes, total_bytes = validate_archive_entries(
                entries,
                known_style_codes,
            )
            free_space = shutil.disk_usage(image_root.parent).free
            if total_bytes + MIN_FREE_SPACE_BYTES > free_space:
                raise ProductImageArchiveError('服务器磁盘空间不足，无法安全解压并替换图片。')

            with TemporaryDirectory(
                prefix='.product-images-import-',
                dir=image_root.parent,
            ) as work_directory:
                work_root = Path(work_directory)
                staging_root = work_root / 'staging'
                staging_root.mkdir()
                extract_validated_entries(archive, entries, staging_root)
                replace_style_directories(
                    staging_root,
                    image_root,
                    style_codes,
                    work_root,
                )
    except BadZipFile as error:
        raise ProductImageArchiveError('上传文件不是有效的 ZIP 压缩包。') from error

    return ProductImageArchiveResult(
        style_codes=tuple(sorted(style_codes)),
        image_count=len(entries),
        uncompressed_bytes=total_bytes,
    )
