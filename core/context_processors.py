from core.models import SiteSettings


def site_settings(request):
    """提供网站联系方式给所有模板"""
    s = SiteSettings.get_settings()
    return {
        'SITE_PHONE': s.phone or '待配置',
        'SITE_EMAIL': s.email or 'sales@example.com',
    }
