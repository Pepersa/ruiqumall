import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from customers.models import ShippingAddress

from .models import RegistrationRequest, UserProfile
from .services import sync_customer_from_profile


# 中国大陆手机号：1 开头 11 位
PHONE_RE = re.compile(r'^1[3-9]\d{9}$')


class RegistrationRequestForm(forms.ModelForm):
    class Meta:
        model = RegistrationRequest
        fields = ('username', 'email', 'company_name', 'contact_name', 'phone', 'purpose')
        labels = {
            'username': '用户名',
            'email': '邮箱',
            'company_name': '公司名称',
            'contact_name': '联系人',
            'phone': '手机号码',
            'purpose': '申请说明',
        }
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': '设置登录用户名'}),
            'email': forms.EmailInput(attrs={'placeholder': '选填'}),
            'company_name': forms.TextInput(attrs={'placeholder': '请输入公司全称'}),
            'contact_name': forms.TextInput(attrs={'placeholder': '请输入联系人姓名'}),
            'phone': forms.TextInput(attrs={'placeholder': '请输入 11 位手机号码', 'inputmode': 'numeric', 'maxlength': '11'}),
            'purpose': forms.Textarea(attrs={'rows': 3, 'placeholder': '选填。请说明采购品类、主要用途等'}),
        }

    password1 = forms.CharField(
        label='设置密码',
        widget=forms.PasswordInput(attrs={'placeholder': '请输入密码'}),
        required=True,
    )
    password2 = forms.CharField(
        label='确认密码',
        widget=forms.PasswordInput(attrs={'placeholder': '请再次输入密码'}),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = '设置后不可修改，请慎重填写'
        self.fields['phone'].required = True
        self.order_fields(
            [
                'username',
                'password1',
                'password2',
                'email',
                'company_name',
                'contact_name',
                'phone',
                'purpose',
            ]
        )

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if not username:
            raise ValidationError('用户名不能为空')
        if len(username) < 3:
            raise ValidationError('用户名至少需要 3 个字符')
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            raise ValidationError('该用户名已被注册，请换一个')
        return username

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if not phone:
            raise ValidationError('请填写手机号码')
        if not PHONE_RE.match(phone):
            raise ValidationError('手机号格式不正确，请输入 11 位中国大陆手机号')
        return phone

    def clean_password1(self):
        p1 = self.cleaned_data.get('password1', '')
        if not p1:
            raise ValidationError('请设置登录密码')
        try:
            validate_password(p1)
        except ValidationError as exc:
            raise ValidationError('; '.join(exc.messages))
        return p1

    def clean_password2(self):
        p1 = self.cleaned_data.get('password1', '')
        p2 = self.cleaned_data.get('password2', '')
        if not p2:
            raise ValidationError('请再次输入密码')
        if p1 != p2:
            raise ValidationError('两次输入的密码不一致')
        return p2

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.status = RegistrationRequest.Status.PENDING
        pwd = self.cleaned_data.get('password1', '')
        if pwd:
            instance.password = make_password(pwd)
        if commit:
            instance.save()
        return instance


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label='邮箱', required=False)
    company_name = forms.CharField(label='公司名称', max_length=180, required=False)
    name = forms.CharField(label='姓名', max_length=80, required=False)
    phone = forms.CharField(label='电话号码', max_length=80, required=False)

    class Meta:
        model = get_user_model()
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['username', 'name', 'phone', 'email', 'company_name', 'password1', 'password2'])

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email', '')
        if commit:
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'name': self.cleaned_data.get('name', ''),
                    'phone': self.cleaned_data.get('phone', ''),
                    'company_name': self.cleaned_data.get('company_name', ''),
                },
            )
            sync_customer_from_profile(user)
        return user


class ProfileForm(forms.Form):
    email = forms.EmailField(label='邮箱', required=False)
    name = forms.CharField(label='姓名', max_length=80, required=False)
    phone = forms.CharField(label='电话号码', max_length=80, required=False)
    company_name = forms.CharField(label='公司名称', max_length=180, required=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        profile = UserProfile.objects.filter(user=user).first()
        self.fields['email'].initial = user.email
        if profile:
            self.fields['name'].initial = profile.name
            self.fields['phone'].initial = profile.phone
            self.fields['company_name'].initial = profile.company_name

    def save(self):
        profile, _ = UserProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'name': self.cleaned_data.get('name', ''),
                'phone': self.cleaned_data.get('phone', ''),
                'company_name': self.cleaned_data.get('company_name', ''),
            },
        )
        self.user.email = self.cleaned_data.get('email', '')
        self.user.save(update_fields=['email'])
        sync_customer_from_profile(self.user)
        return profile


class ShippingAddressForm(forms.ModelForm):
    class Meta:
        model = ShippingAddress
        fields = (
            'label',
            'receiver_name',
            'receiver_mobile',
            'receiver_state',
            'receiver_city',
            'receiver_district',
            'receiver_address',
            'is_default',
        )
        labels = {
            'label': '地址标签',
            'receiver_name': '收货人姓名',
            'receiver_mobile': '手机号码',
            'receiver_state': '省',
            'receiver_city': '市',
            'receiver_district': '区/街道',
            'receiver_address': '详细地址',
            'is_default': '设为默认收货地址，下单时会优先使用该地址',
        }
        widgets = {
            'label': forms.HiddenInput(),
            'receiver_name': forms.TextInput(attrs={'placeholder': '请输入收货人姓名'}),
            'receiver_mobile': forms.TextInput(attrs={'placeholder': '请输入手机号码'}),
            'receiver_state': forms.TextInput(attrs={'placeholder': '省'}),
            'receiver_city': forms.TextInput(attrs={'placeholder': '市'}),
            'receiver_district': forms.TextInput(attrs={'placeholder': '区/街道'}),
            'receiver_address': forms.Textarea(
                attrs={
                    'rows': 3,
                    'placeholder': '请输入道路、小区、单元楼、门牌号等详细信息',
                }
            ),
            'is_default': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['receiver_state'].required = True
        self.fields['receiver_city'].required = True
        self.fields['receiver_district'].required = False
        self.fields['receiver_address'].required = True
        self.fields['receiver_name'].required = True
        self.fields['receiver_mobile'].required = True
        self.order_fields(
            [
                'receiver_state',
                'receiver_city',
                'receiver_district',
                'receiver_address',
                'receiver_name',
                'receiver_mobile',
                'is_default',
                'label',
            ]
        )

