from .views import root_categories


def category_navigation(request):
    return {'category_tree': root_categories()}
