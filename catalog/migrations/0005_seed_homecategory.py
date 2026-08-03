from django.db import migrations


UNCATEGORIZED_SLUG = 'uncategorized'


def create_home_categories(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    HomeCategory = apps.get_model('catalog', 'HomeCategory')

    second_level = (
        Category.objects
        .filter(
            is_active=True,
            parent__isnull=False,
            parent__parent__isnull=True,
            parent__is_active=True,
        )
        .exclude(parent__slug=UNCATEGORIZED_SLUG)
        .order_by('parent__sort_order', 'parent__name', 'sort_order', 'name')
    )

    existing_ids = set(
        HomeCategory.objects.filter(category_id__in=[c.id for c in second_level])
        .values_list('category_id', flat=True)
    )

    to_create = []
    sort = 0
    for cat in second_level:
        if cat.id in existing_ids:
            continue
        to_create.append(HomeCategory(
            category_id=cat.id,
            title='',
            image='',
            link_url='',
            sort_order=sort,
            is_active=True,
        ))
        sort += 1

    if to_create:
        HomeCategory.objects.bulk_create(to_create)


def remove_home_categories(apps, schema_editor):
    Category = apps.get_model('catalog', 'Category')
    HomeCategory = apps.get_model('catalog', 'HomeCategory')

    second_level_ids = list(
        Category.objects
        .filter(
            parent__isnull=False,
            parent__parent__isnull=True,
        )
        .exclude(parent__slug=UNCATEGORIZED_SLUG)
        .values_list('id', flat=True)
    )
    HomeCategory.objects.filter(category_id__in=second_level_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0004_homecategory'),
    ]

    operations = [
        migrations.RunPython(create_home_categories, remove_home_categories),
    ]
