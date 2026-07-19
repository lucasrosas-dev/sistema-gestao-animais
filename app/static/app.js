(() => {
  const toggle = document.getElementById('menuToggle');
  toggle?.addEventListener('click', () => {
    const open = document.body.classList.toggle('sidebar-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (event) => {
    const form = event.target.closest('form[data-confirm]');
    if (form && event.target.matches('button[type="submit"]')) {
      if (!window.confirm(form.dataset.confirm || 'Confirma esta operação?')) event.preventDefault();
    }
  });
  document.querySelectorAll('form.prevent-double-submit').forEach(form => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('button[type="submit"]');
      if (button) { button.disabled = true; button.textContent = 'Salvando...'; }
    });
  });
  if (window.innerWidth < 900) document.querySelectorAll('.sidebar a').forEach(link => link.addEventListener('click', () => document.body.classList.remove('sidebar-open')));
  const now = new Date();
  const localDate = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  document.querySelectorAll('input[type="date"][data-default-today], input[name="data_movimentacao"]').forEach(input => { if (!input.value) input.value = localDate; });
  document.querySelectorAll('[data-current-datetime]').forEach(el => { el.textContent = now.toLocaleString('pt-BR'); });
})();

function showConditional(id, show) {
  const element = document.getElementById(id);
  if (element) element.hidden = !show;
}

function initCostForm() {
  const type = document.getElementById('costType') || document.querySelector('[name="tipo_apropriacao"]');
  const method = document.getElementById('allocationMethod') || document.querySelector('[name="metodo_rateio"]');
  const refresh = () => {
    const value = type?.value || '';
    showConditional('directAnimalField', value === 'Custo direto de animal');
    showConditional('groupAllocation', value === 'Custo de grupo de animais');
    showConditional('percentageAllocation', value === 'Custo de grupo de animais' && method?.value === 'Rateio percentual manual');
    showConditional('valueAllocation', value === 'Custo de grupo de animais' && method?.value === 'Rateio por valor manual');
  };
  type?.addEventListener('change', refresh); method?.addEventListener('change', refresh); refresh();
  const quantity = document.querySelector('[name="quantidade"]');
  const unit = document.querySelector('[name="valor_unitario"]');
  const total = document.querySelector('[name="valor_total"]');
  [quantity, unit].forEach(input => input?.addEventListener('input', () => {
    const q = Number(String(quantity?.value || '').replace('.','').replace(',','.'));
    const u = Number(String(unit?.value || '').replace('.','').replace(',','.'));
    if (Number.isFinite(q) && Number.isFinite(u) && q > 0 && u >= 0 && total) total.value = (q*u).toFixed(2).replace('.',',');
  }));
}

function initRevenueForm() {
  const category = document.querySelector('[name="categoria"]');
  const section = document.getElementById('revenueAnimalField');
  const animal = section?.querySelector('[name="animal_id"]');
  const refresh = () => {
    const sale = category?.value === 'Venda de animal';
    if (section) section.hidden = !sale;
    if (animal) animal.required = sale;
  };
  category?.addEventListener('change', refresh); refresh();
  const quantity = document.querySelector('[name="quantidade"]');
  const unit = document.querySelector('[name="valor_unitario"]');
  const total = document.querySelector('[name="valor_total"]');
  [quantity, unit].forEach(input => input?.addEventListener('input', () => {
    const q = Number(String(quantity?.value || '').replace('.','').replace(',','.'));
    const u = Number(String(unit?.value || '').replace('.','').replace(',','.'));
    if (Number.isFinite(q) && Number.isFinite(u) && q > 0 && u >= 0 && total) total.value = (q*u).toFixed(2).replace('.',',');
  }));
}

function initEventForm(groups) {
  const group = document.querySelector('[name="grupo"]');
  const type = document.querySelector('[name="tipo"]');
  const current = type?.dataset.selected || type?.value;
  const refresh = () => {
    if (!type) return;
    const items = groups[group?.value] || [];
    const wanted = type.value || current;
    type.innerHTML = '<option value="">Selecione</option>' + items.map(item => `<option value="${item}">${item}</option>`).join('');
    if (items.includes(wanted)) type.value = wanted;
    showConditional('birthSection', group?.value === 'Reprodutivo' && type.value === 'Parto');
  };
  group?.addEventListener('change', refresh); type?.addEventListener('change', refresh); refresh();
}
