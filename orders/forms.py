from django import forms


class OrderConfirmForm(forms.Form):
    saved_address = forms.ChoiceField(label='选择收货地址', required=False)
    receiver_name = forms.CharField(label='收件人', max_length=80)
    receiver_mobile = forms.CharField(label='收件电话', max_length=80)
    receiver_state = forms.CharField(label='省', max_length=80, required=False)
    receiver_city = forms.CharField(label='市', max_length=80, required=False)
    receiver_district = forms.CharField(label='区', max_length=80, required=False)
    receiver_address = forms.CharField(label='详细地址', max_length=255)
    buyer_message = forms.CharField(label='买家留言', required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        choices = [('', '手动填写')]
        for address in user.shipping_addresses.all():
            label = address.label or address.receiver_name
            summary = f'{label} · {address.receiver_state}{address.receiver_city}{address.receiver_district}{address.receiver_address}'
            choices.append((str(address.pk), summary))
        self.fields['saved_address'].choices = choices

    def order_payload(self):
        return self.cleaned_data.copy()
