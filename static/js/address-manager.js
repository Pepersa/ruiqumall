(function () {
  function maskPhone(value) {
    const text = String(value || '');
    if (text.length >= 7) {
      return `${text.slice(0, 3)}****${text.slice(-4)}`;
    }
    return text;
  }

  function readCard(card) {
    return {
      id: card.dataset.addressId,
      label: card.dataset.addressLabel || '',
      receiverName: card.dataset.receiverName || '',
      receiverMobile: card.dataset.receiverMobile || '',
      receiverState: card.dataset.receiverState || '',
      receiverCity: card.dataset.receiverCity || '',
      receiverDistrict: card.dataset.receiverDistrict || '',
      receiverAddress: card.dataset.receiverAddress || '',
    };
  }

  function regionText(data) {
    return `${data.receiverState}${data.receiverCity}${data.receiverDistrict}`;
  }

  class AddressManager {
    constructor(root) {
      this.root = root;
      this.modal = document.getElementById('address-modal');
      if (!this.modal) {
        return;
      }

      this.mode = root.dataset.addressManager || 'checkout';
      this.form = root.querySelector('[data-order-form]');
      this.summary = root.querySelector('[data-address-summary]');
      this.modalForm = this.modal.querySelector('#address-modal-form');
      this.saveButton = this.modal.querySelector('#address-modal-save');
      this.tabs = this.modal.querySelectorAll('[data-address-tab]');
      this.panes = this.modal.querySelectorAll('[data-address-pane]');
      this.cards = this.modal.querySelectorAll('.address-grid-card');
      this.labelInput = this.modal.querySelector('#address-form-label');
      this.labelTags = this.modal.querySelector('[data-label-tags]');
      this.selectedCard = this.modal.querySelector('.address-grid-card.is-selected') || this.cards[0] || null;

      this.bindEvents();
      if (this.mode === 'checkout' && this.form) {
        this.syncSummaryFromForm();
      }
    }

    bindEvents() {
      document.querySelectorAll('[data-open-address-modal]').forEach((button) => {
        button.addEventListener('click', () => {
          const tab = button.dataset.openAddressModal || 'switch';
          if (tab === 'add') {
            this.resetCreateForm();
          }
          this.openModal(tab);
        });
      });

      this.modal.querySelectorAll('[data-close-address-modal]').forEach((button) => {
        button.addEventListener('click', () => this.closeModal());
      });

      this.tabs.forEach((tab) => {
        tab.addEventListener('click', () => this.switchTab(tab.dataset.addressTab));
      });

      this.cards.forEach((card) => {
        card.addEventListener('click', (event) => {
          if (event.target.closest('form, button, a')) {
            return;
          }
          this.selectCard(card);
        });
        card.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            this.selectCard(card);
          }
        });
      });

      this.modal.querySelectorAll('[data-edit-address]').forEach((button) => {
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          const card = button.closest('.address-grid-card');
          if (card) {
            this.loadCardIntoForm(card);
            this.openModal('add');
          }
        });
      });

      document.querySelectorAll('[data-edit-address]').forEach((button) => {
        if (this.modal.contains(button)) {
          return;
        }
        button.addEventListener('click', (event) => {
          event.stopPropagation();
          const card = button.closest('.address-grid-card');
          if (card) {
            this.loadCardIntoForm(card);
            this.openModal('add');
          }
        });
      });

      this.saveButton.addEventListener('click', () => {
        const activeTab = this.modal.querySelector('.address-modal-tab.active');
        if (activeTab && activeTab.dataset.addressTab === 'add') {
          this.modalForm.requestSubmit();
          return;
        }
        if (this.mode === 'checkout') {
          this.applySelection();
        }
        this.closeModal();
      });

      if (this.labelTags) {
        this.labelTags.querySelectorAll('[data-label-value]').forEach((button) => {
          button.addEventListener('click', () => {
            this.labelTags.querySelectorAll('.address-label-tag').forEach((item) => item.classList.remove('active'));
            button.classList.add('active');
            this.labelInput.value = button.dataset.labelValue;
            this.labelTags.querySelector('.address-label-custom').value = '';
          });
        });
        const customInput = this.labelTags.querySelector('.address-label-custom');
        customInput.addEventListener('input', () => {
          this.labelTags.querySelectorAll('.address-label-tag').forEach((item) => item.classList.remove('active'));
          this.labelInput.value = customInput.value.trim();
        });
      }

    }

    openModal(tab) {
      this.modal.hidden = false;
      document.body.classList.add('modal-open');
      this.switchTab(tab || 'switch');
    }

    closeModal() {
      this.modal.hidden = true;
      document.body.classList.remove('modal-open');
    }

    switchTab(tabName) {
      this.tabs.forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.addressTab === tabName);
      });
      this.panes.forEach((pane) => {
        const active = pane.dataset.addressPane === tabName;
        pane.classList.toggle('active', active);
        pane.hidden = !active;
      });
      this.saveButton.dataset.addressSaveMode = tabName === 'add' ? 'add' : 'switch';
    }

    selectCard(card) {
      this.cards.forEach((item) => item.classList.remove('is-selected'));
      card.classList.add('is-selected');
      this.selectedCard = card;
    }

    applySelection() {
      if (!this.selectedCard || !this.form) {
        return;
      }
      const data = readCard(this.selectedCard);
      this.setField('saved_address', data.id);
      this.setField('receiver_name', data.receiverName);
      this.setField('receiver_mobile', data.receiverMobile);
      this.setField('receiver_state', data.receiverState);
      this.setField('receiver_city', data.receiverCity);
      this.setField('receiver_district', data.receiverDistrict);
      this.setField('receiver_address', data.receiverAddress);
      this.renderSummary(data);
    }

    setField(name, value) {
      const field = this.form.querySelector(`[name="${name}"]`);
      if (field) {
        field.value = value || '';
      }
    }

    syncSummaryFromForm() {
      const data = {
        label: '',
        receiverName: this.form.querySelector('[name="receiver_name"]')?.value || '',
        receiverMobile: this.form.querySelector('[name="receiver_mobile"]')?.value || '',
        receiverState: this.form.querySelector('[name="receiver_state"]')?.value || '',
        receiverCity: this.form.querySelector('[name="receiver_city"]')?.value || '',
        receiverDistrict: this.form.querySelector('[name="receiver_district"]')?.value || '',
        receiverAddress: this.form.querySelector('[name="receiver_address"]')?.value || '',
      };
      const card = this.modal.querySelector(`.address-grid-card[data-address-id="${this.form.querySelector('[name="saved_address"]')?.value}"]`);
      if (card) {
        data.label = card.dataset.addressLabel || '';
      }
      if (data.receiverName || data.receiverAddress) {
        this.renderSummary(data);
      }
    }

    renderSummary(data) {
      if (!this.summary) {
        return;
      }
      const hasAddress = Boolean(data.receiverAddress);
      this.summary.hidden = !hasAddress;
      if (!hasAddress) {
        return;
      }
      const tag = this.summary.querySelector('[data-summary-tag]');
      tag.textContent = data.label || '';
      tag.hidden = !data.label;
      this.summary.querySelector('[data-summary-region]').textContent = regionText(data);
      this.summary.querySelector('[data-summary-line]').textContent = data.receiverAddress;
      this.summary.querySelector('[data-summary-contact]').textContent =
        `${data.receiverName} ${maskPhone(data.receiverMobile)}`;
    }

    loadCardIntoForm(card) {
      const data = readCard(card);
      this.modalForm.action = `/accounts/profile/addresses/${card.dataset.addressId}/edit/`;
      this.setFormField('receiver_state', data.receiverState);
      this.setFormField('receiver_city', data.receiverCity);
      this.setFormField('receiver_district', data.receiverDistrict);
      this.setFormField('receiver_address', data.receiverAddress);
      this.setFormField('receiver_name', data.receiverName);
      this.setFormField('receiver_mobile', data.receiverMobile);
      this.labelInput.value = data.label;
      if (this.labelTags) {
        this.labelTags.querySelectorAll('.address-label-tag').forEach((button) => {
          button.classList.toggle('active', button.dataset.labelValue === data.label);
        });
        this.labelTags.querySelector('.address-label-custom').value =
          ['家', '公司', '学校'].includes(data.label) ? '' : data.label;
      }
    }

    resetCreateForm() {
      this.modalForm.action = this.modalForm.dataset.createUrl;
      this.modalForm.reset();
      this.labelInput.value = '';
      if (this.labelTags) {
        this.labelTags.querySelectorAll('.address-label-tag').forEach((item) => item.classList.remove('active'));
        this.labelTags.querySelector('.address-label-custom').value = '';
      }
    }

    setFormField(name, value) {
      const field = this.modalForm.querySelector(`[name="${name}"]`);
      if (field) {
        field.value = value || '';
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-address-manager]').forEach((root) => {
      root.addressManager = new AddressManager(root);
    });

    const params = new URLSearchParams(window.location.search);
    const managerRoot = document.querySelector('[data-address-manager="profile"]');
    if (managerRoot && managerRoot.addressManager) {
      const open = params.get('open');
      if (open === 'add') {
        managerRoot.addressManager.resetCreateForm();
        managerRoot.addressManager.openModal('add');
      } else if (open && open.startsWith('edit-')) {
        const id = open.replace('edit-', '');
        const card = document.querySelector(`.address-grid-card[data-address-id="${id}"]`);
        if (card) {
          managerRoot.addressManager.loadCardIntoForm(card);
          managerRoot.addressManager.openModal('add');
        }
      }
    }
  });
})();
