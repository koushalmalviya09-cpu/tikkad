let csrfToken = '';
let bookings = [];

const loginPanel = document.querySelector('#login-panel');
const dashboardPanel = document.querySelector('#dashboard-panel');
const loginForm = document.querySelector('#staff-login-form');
const loginError = document.querySelector('#login-error');

async function login(code) {
  const response = await fetch('/api/staff/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Login failed');
  csrfToken = data.csrfToken;
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  const code = document.querySelector('#staff-code').value;
  try {
    await login(code);
    loginPanel.hidden = true;
    dashboardPanel.hidden = false;
    await loadBookings();
  } catch (error) {
    loginError.textContent = error.message;
  }
});

async function loadBookings() {
  const response = await fetch('/api/staff/bookings');
  if (response.status === 401) {
    dashboardPanel.hidden = true;
    loginPanel.hidden = false;
    return;
  }
  const data = await response.json();
  bookings = data.bookings || [];
  renderBookings();
}

function escapeHtml(value) {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}

function formatDateTime(booking) {
  const date = new Date(`${booking.booking_date}T${booking.booking_time}:00`);
  if (Number.isNaN(date.getTime())) return `${booking.booking_date} · ${booking.booking_time}`;
  return `${date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })} · ${booking.booking_time}`;
}

function formatReceived(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

function renderBookings() {
  const search = document.querySelector('#booking-search').value.trim().toLowerCase();
  const status = document.querySelector('#status-filter').value;

  const filtered = bookings.filter((booking) => {
    const matchesSearch = !search || booking.name.toLowerCase().includes(search) || booking.phone.includes(search);
    const matchesStatus = status === 'all' || booking.status === status;
    return matchesSearch && matchesStatus;
  });

  document.querySelector('#total-count').textContent = bookings.length;
  document.querySelector('#new-count').textContent = bookings.filter((booking) => booking.status === 'new').length;
  document.querySelector('#confirmed-count').textContent = bookings.filter((booking) => booking.status === 'confirmed').length;

  const today = new Date().toISOString().slice(0, 10);
  document.querySelector('#today-count').textContent = bookings
    .filter((booking) => booking.booking_date === today && booking.status !== 'cancelled')
    .reduce((total, booking) => total + booking.guests, 0);

  const rows = document.querySelector('#booking-rows');
  rows.innerHTML = filtered.map((booking) => `
    <tr>
      <td><strong>${escapeHtml(booking.name)}</strong></td>
      <td><a href="tel:${escapeHtml(booking.phone)}">${escapeHtml(booking.phone)}</a></td>
      <td>${formatDateTime(booking)}</td>
      <td>${booking.guests}</td>
      <td>
        <select class="status-select" data-id="${booking.id}" aria-label="Booking status">
          <option value="new" ${booking.status === 'new' ? 'selected' : ''}>New</option>
          <option value="confirmed" ${booking.status === 'confirmed' ? 'selected' : ''}>Confirmed</option>
          <option value="cancelled" ${booking.status === 'cancelled' ? 'selected' : ''}>Cancelled</option>
        </select>
      </td>
      <td>${formatReceived(booking.created_at)}</td>
      <td><button class="delete-booking" data-id="${booking.id}" type="button" aria-label="Delete booking">Delete</button></td>
    </tr>
  `).join('');

  document.querySelector('#empty-state').hidden = filtered.length !== 0;
}

document.querySelector('#booking-search').addEventListener('input', renderBookings);
document.querySelector('#status-filter').addEventListener('change', renderBookings);
document.querySelector('#refresh-button').addEventListener('click', loadBookings);

document.querySelector('#booking-rows').addEventListener('change', async (event) => {
  if (!event.target.matches('.status-select')) return;
  await fetch(`/api/staff/bookings/${event.target.dataset.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
    body: JSON.stringify({ status: event.target.value })
  });
  await loadBookings();
});

document.querySelector('#booking-rows').addEventListener('click', async (event) => {
  if (!event.target.matches('.delete-booking')) return;
  if (!confirm('Delete this booking permanently?')) return;
  await fetch(`/api/staff/bookings/${event.target.dataset.id}`, {
    method: 'DELETE',
    headers: { 'X-CSRF-Token': csrfToken }
  });
  await loadBookings();
});

document.querySelector('#logout-button').addEventListener('click', async () => {
  await fetch('/api/staff/logout', {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrfToken }
  });
  csrfToken = '';
  dashboardPanel.hidden = true;
  loginPanel.hidden = false;
  loginForm.reset();
});

fetch('/api/staff/bookings').then(async (response) => {
  if (response.status === 401) return;
  const data = await response.json();
  bookings = data.bookings || [];
  dashboardPanel.hidden = false;
  loginPanel.hidden = true;
  const sessionResponse = await fetch('/api/staff/session');
  if (sessionResponse.ok) {
    const sessionData = await sessionResponse.json();
    csrfToken = sessionData.csrfToken;
  }
  renderBookings();
});
