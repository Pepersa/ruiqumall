from pathlib import Path

from django.conf import settings
from django.urls import reverse


IMAGE_EXTENSIONS = {
    '.avif',
    '.jpeg',
    '.jpg',
    '.png',
    '.webp',
}
DETAIL_DIRECTORY_NAMES = ('详情页', '详情图')


def product_image_root():
    return Path(
        getattr(
            settings,
            'PRODUCT_IMAGE_ROOT',
            settings.MEDIA_ROOT / 'product_catalog',
        )
    )


def safe_directory(root, *parts):
    resolved_root = Path(root).resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return None
    return candidate


def product_style_directory(product):
    return safe_directory(product_image_root(), product.style_code)


def is_image_file(path):
    return path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS


def image_url(path):
    relative_path = path.relative_to(product_image_root()).as_posix()
    return reverse('catalog:product_media', kwargs={'asset_path': relative_path})


def product_asset_directory(product, selected_sku=None):
    style_root = product_style_directory(product)
    if not style_root or not style_root.is_dir():
        return None

    if selected_sku:
        sku_root = safe_directory(style_root, selected_sku.internal_sku_code)
        if sku_root and sku_root.is_dir():
            return sku_root

    return style_root


def main_image_from_directory(asset_directory):
    main_directory = asset_directory / '主图透图'
    if not main_directory.is_dir():
        return None

    images = sorted(
        (path for path in main_directory.iterdir() if is_image_file(path)),
        key=lambda path: path.name.casefold(),
    )
    if not images:
        return None

    named_main = next(
        (path for path in images if path.name.casefold().startswith('主图.')),
        None,
    )
    return named_main or images[0]


def sku_main_image_from_directory(sku_directory):
    """新格式 SKU 子目录主图：取按文件名自然排序的第一张图片。"""
    if not sku_directory or not sku_directory.is_dir():
        return None
    candidates = [path for path in sku_directory.iterdir() if is_image_file(path)]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.name.casefold())
    return candidates[0]


def sku_detail_images_from_directory(sku_directory):
    """新格式 SKU 子目录详情图：除第一张以外全部图片，索引从 2 开始。"""
    if not sku_directory or not sku_directory.is_dir():
        return []
    candidates = sorted(
        (path for path in sku_directory.iterdir() if is_image_file(path)),
        key=lambda path: path.name.casefold(),
    )
    return candidates[1:]


def detail_images_from_directory(asset_directory):
    for directory_name in DETAIL_DIRECTORY_NAMES:
        detail_directory = asset_directory / directory_name
        if not detail_directory.is_dir():
            continue
        images = sorted(
            (path for path in detail_directory.iterdir() if is_image_file(path)),
            key=lambda path: path.name.casefold(),
        )
        if images:
            return images
    return []


def product_image_gallery(product, selected_sku=None):
    asset_directory = product_asset_directory(product, selected_sku)
    if not asset_directory:
        return {'main_url': product.display_image_url, 'detail_images': []}

    # 新格式：直接平铺在 SKU 子目录的图片（如 DR-CT-01-YR03-1.jpg）。
    # product_asset_directory 已经下钻到 SKU 子目录（style_code/<sku_code>/），
    # 所以这里直接对 asset_directory 查平铺命名即可。
    flat_main = sku_main_image_from_directory(asset_directory)
    if flat_main is not None:
        flat_details = sku_detail_images_from_directory(asset_directory)
        return {
            'main_url': image_url(flat_main),
            'detail_images': [
                {
                    'url': image_url(path),
                    'alt': f'{product.name} 产品详情图 {index}',
                }
                for index, path in enumerate(flat_details, start=2)
            ],
        }

    main_image = main_image_from_directory(asset_directory)
    detail_images = detail_images_from_directory(asset_directory)
    return {
        'main_url': image_url(main_image) if main_image else product.display_image_url,
        'detail_images': [
            {
                'url': image_url(path),
                'alt': f'{product.name} 产品详情图 {index}',
            }
            for index, path in enumerate(detail_images, start=1)
        ],
    }


def product_main_image_url(product, selected_sku=None):
    asset_directory = product_asset_directory(product, selected_sku)
    if not asset_directory:
        return product.display_image_url

    flat_main = sku_main_image_from_directory(asset_directory)
    if flat_main is not None:
        return image_url(flat_main)

    main_image = main_image_from_directory(asset_directory)
    return image_url(main_image) if main_image else product.display_image_url


def product_attachments_gallery(product, max_main_detail=12, max_detail=10):
    """
    Return a combined gallery list for the product detail page:
    1. Product main image (from product.image)
    2. Up to max_main_detail images from product attachments with numeric prefix (main detail images)
    3. Up to max_detail images with 'd' prefix (detail images)
    4. Carousel images uploaded via admin (轮播图 prefix)
    """
    images = []

    # 1. Product main image
    if product.image:
        images.append({
            'url': product.image.url,
            'type': 'main',
            'alt': f'{product.name} 产品主图',
        })

    # 2. Main detail images (numeric prefix 1..N, sorted by number)
    qs = product.attachments.filter(is_public=True).order_by('file')
    numbered_images = []
    detail_images = []
    carousel_images = []

    for att in qs:
        fname = att.file.name.split('/')[-1]
        parts = fname.split('_', 1)
        prefix = parts[0]

        if prefix.isdigit():
            numbered_images.append((int(prefix), att))
        elif prefix.startswith('d') and prefix[1:].isdigit():
            detail_images.append((int(prefix[1:]), att))
        elif att.title and att.title.startswith('轮播图'):
            carousel_images.append(att)

    numbered_images.sort(key=lambda x: x[0])
    detail_images.sort(key=lambda x: x[0])

    for idx, (_, att) in enumerate(numbered_images[:max_main_detail]):
        images.append({
            'url': att.file.url,
            'type': 'main_detail',
            'alt': f'{product.name} 主图细节 {idx + 1}',
        })

    for idx, (_, att) in enumerate(detail_images[:max_detail]):
        images.append({
            'url': att.file.url,
            'type': 'detail',
            'alt': f'{product.name} 详情图 {idx + 1}',
        })

    # 3. Carousel images (from admin upload)
    for att in carousel_images:
        images.append({
            'url': att.file.url,
            'type': 'carousel',
            'alt': f'{product.name} 轮播图',
        })

    return images


def product_documents(product):
    """Return list of downloadable documents for this product."""
    return [
        att for att in product.attachments.filter(is_public=True)
        if not att.title.startswith('轮播图')
        and not att.file.name.split('/')[-1].split('_')[0].isdigit()
        and not att.file.name.split('/')[-1].split('_')[0].startswith('d')
        and not att.file.name.split('/')[-1].split('_')[0].startswith('0_')
    ]
