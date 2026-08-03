"""上架模板配套的图片 ZIP 上传：

压缩包结构（平铺命名）：
    <sku_code>-<seq>.<ext>     # 第一张主图，第二张起为详情图
    <sku_code>-1.jpg          → SKU 的主图
    <sku_code>-2.jpg          → SKU 的详情图 1
    ...

zip 根目录下若存在一个统一目录（如 "上架测试 2/"），自动剥离后处理。
"""
from __future__ import annotations

import re
import shutil
import stat
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from django.db.models import Q

from .models import Product, SKU
from .product_images import IMAGE_EXTENSIONS, product_image_root, safe_directory


MAX_ARCHIVE_FILES = 50_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 10 * 1024 ** 3
MIN_FREE_SPACE_BYTES = 200 * 1024 ** 2
_IGNORED_ARCHIVE_NAMES = {'.DS_Store'}


class ListingImageImportError(ValueError):
    pass


@dataclass
class ListingImageImportResult:
    style_codes: tuple[str, ...] = field(default_factory=tuple)
    sku_codes: tuple[str, ...] = field(default_factory=tuple)
    image_count: int = 0
    uncompressed_bytes: int = 0
    missing_skus: tuple[str, ...] = field(default_factory=tuple)


_FILENAME_PATTERN = re.compile(
    r'^([A-Za-z0-9._\-]+?)-(\d+)(\.[A-Za-z0-9]+)?$',
)


def parse_image_filename(filename: str):
    """匹配 `<sku>-<seq>.<ext>`，返回 (sku_code, seq, suffix) 或 None。"""
    parts = _FILENAME_PATTERN.match(filename)
    if not parts:
        return None
    sku_code = parts.group(1).strip()
    if not sku_code:
        return None
    try:
        seq = int(parts.group(2))
    except ValueError:
        return None
    suffix = (parts.group(3) or '').lower()
    return sku_code, seq, suffix


def normalized_archive_parts(name: str):
    normalized = name.replace('\\', '/')
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in path.parts):
        raise ListingImageImportError(f'压缩包包含不安全路径：{name}')
    return path.parts


def is_symbolic_link(info) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def iter_archive_entries(archive: ZipFile):
    entries = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = normalized_archive_parts(info.filename)
        if parts[0] == '__MACOSX' or parts[-1] in _IGNORED_ARCHIVE_NAMES:
            continue
        if is_symbolic_link(info):
            raise ListingImageImportError(f'压缩包不能包含符号链接：{info.filename}')
        if info.flag_bits & 0x1:
            raise ListingImageImportError(f'压缩包不能包含加密文件：{info.filename}')
        entries.append((info, parts))
    if not entries:
        raise ListingImageImportError('压缩包中没有可识别的图片文件。')
    return entries


def strip_optional_root(entries):
    """剥离常见的单一顶层目录，如 `上架测试 2/`、`product_catalog/`。"""
    if not entries:
        return entries
    top_dirs = {parts[0] for _, parts in entries if len(parts) > 1}
    if len(top_dirs) == 1:
        top = next(iter(top_dirs))
        stripped = []
        for info, parts in entries:
            if len(parts) <= 1:
                continue
            stripped.append((info, parts[1:]))
        if stripped:
            return stripped
    return entries


def validate_image_entries(entries):
    if len(entries) > MAX_ARCHIVE_FILES:
        raise ListingImageImportError(f'压缩包文件数量不能超过 {MAX_ARCHIVE_FILES}。')

    sku_index: dict[str, list[tuple[int, str, object]]] = defaultdict(list)
    total_bytes = 0
    validated = []
    seen_paths = set()

    for info, parts in entries:
        if len(parts) != 1:
            raise ListingImageImportError(
                f'图片文件必须位于压缩包根目录：{info.filename}（不支持嵌套目录）'
            )
        filename = parts[0]
        suffix = Path(filename).suffix.casefold()
        if suffix not in IMAGE_EXTENSIONS:
            raise ListingImageImportError(f'文件不是支持的图片格式：{filename}')

        parsed = parse_image_filename(filename)
        if not parsed:
            raise ListingImageImportError(
                f'文件名不符合 <商品编码>-<序号>.<ext> 规则：{filename}'
            )
        sku_code, seq, _suffix = parsed

        if filename in seen_paths:
            raise ListingImageImportError(f'压缩包包含重复文件：{filename}')
        seen_paths.add(filename)

        sku_index[sku_code].append((seq, suffix, info))
        total_bytes += info.file_size
        if total_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ListingImageImportError('压缩包解压后的总大小不能超过 10 GB。')
        validated.append((info, sku_code, seq, suffix))

    return validated, sku_index, total_bytes


def extract_image(uploaded_file, sku_code: str, seq: int, suffix: str, info, target_path: Path):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()
    target = target_path.with_suffix(suffix)
    temporary = target_path.with_suffix(suffix + f'.upload.tmp')
    with uploaded_file.open(info) as source, temporary.open('xb') as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    temporary.replace(target)


def import_listing_image_archive(uploaded_file) -> ListingImageImportResult:
    image_root = Path(product_image_root()).resolve()
    image_root.parent.mkdir(parents=True, exist_ok=True)
    image_root.mkdir(parents=True, exist_ok=True)

    # 预先加载 已知 style_code 与 sku_code 关系
    sku_to_style: dict[str, str] = dict(
        SKU.objects.filter(status__in=['published', 'draft']).values_list('internal_sku_code', 'product__style_code')
    )

    try:
        uploaded_file.seek(0)
        with ZipFile(uploaded_file) as archive:
            raw_entries = iter_archive_entries(archive)
            stripped = strip_optional_root(raw_entries)
            validated, sku_index, total_bytes = validate_image_entries(stripped)

            free_space = shutil.disk_usage(image_root.parent).free
            if total_bytes + MIN_FREE_SPACE_BYTES > free_space:
                raise ListingImageImportError('服务器磁盘空间不足，无法安全解压。')

            unknown_skus = set(sku_index.keys()) - set(sku_to_style.keys())
            if unknown_skus:
                # 仅允许前台用户上传的商品编码通过；后台静默忽略可由 caller 决定
                pass

            with TemporaryDirectory(prefix='.listing-images-', dir=image_root.parent) as workdir:
                work_root = Path(workdir)
                staging_root = work_root / 'staging'
                staging_root.mkdir()
                style_dirs: dict[str, Path] = {}
                summary_skus = set()
                count = 0

                # 仅对已有 SKU 写入；未在数据库中找到的图片保留在解压目录
                # 由调用者决定后续。
                for info, sku_code, seq, suffix in validated:
                    style_code = sku_to_style.get(sku_code)
                    if not style_code:
                        continue
                    summary_skus.add(sku_code)
                    style_root = safe_directory(image_root, style_code)
                    if not style_root:
                        raise ListingImageImportError(f'款式目录不安全：{style_code}')
                    sku_directory = safe_directory(style_root, sku_code)
                    if not sku_directory:
                        raise ListingImageImportError(f'SKU 目录不安全：{sku_code}')
                    sku_directory.mkdir(parents=True, exist_ok=True)
                    style_dirs[style_code] = style_root
                    target = sku_directory / f'{sku_code}-{seq}{suffix}'
                    extract_image(archive, sku_code, seq, suffix, info, target)
                    count += 1

    except BadZipFile as error:
        raise ListingImageImportError('上传文件不是有效的 ZIP 压缩包。') from error

    return ListingImageImportResult(
        style_codes=tuple(sorted(style_dirs.keys())),
        sku_codes=tuple(sorted(summary_skus)),
        image_count=count,
        uncompressed_bytes=total_bytes,
        missing_skus=tuple(sorted({code for code in sku_index.keys() if code not in sku_to_style})),
    )
