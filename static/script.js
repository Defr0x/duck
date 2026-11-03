// === НейроЧат: формы, баланс и чат ===

document.addEventListener('DOMContentLoaded', () => {
    setupPasswordToggles();

    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', (event) => {
            event.preventDefault();
            handleLogin(loginForm);
        });
    }

    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', (event) => {
            event.preventDefault();
            handleRegister(registerForm);
        });
    }

    if (document.getElementById('topupAmount')) {
        setupTopup();
    }

    if (document.getElementById('chat-form')) {
        setupChat();
    }
});

// ---------- Утилиты ----------

function setupPasswordToggles() {
    document.querySelectorAll('.toggle-pass').forEach((button) => {
        button.addEventListener('click', () => {
            const input = button.parentElement.querySelector('input');
            if (!input) return;
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.textContent = show ? '🙈' : '👁';
            button.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
        });
    });
}

function showAlert(message, id = 'error-msg', kind = 'error') {
    const box = document.getElementById(id);
    if (!box) return;
    box.textContent = message;
    box.classList.toggle('ok', kind === 'ok');
    box.classList.add('show');
}

function hideAlert(id = 'error-msg') {
    const box = document.getElementById(id);
    if (!box) return;
    box.textContent = '';
    box.classList.remove('show', 'ok');
}

// POST JSON с блокировкой кнопки на время запроса
async function postJson(button, url, payload) {
    const originalText = button ? button.textContent : null;
    if (button) {
        button.disabled = true;
        button.textContent = 'Подождите…';
    }
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = {};
        }
        return { ok: response.ok, status: response.status, data };
    } catch (error) {
        return { ok: false, status: 0, data: { error: 'Нет соединения с сервером' } };
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalText;
        }
    }
}

// ---------- Вход и регистрация ----------

async function handleLogin(form) {
    hideAlert();
    const email = form.querySelector('#email').value.trim();
    const password = form.querySelector('#password').value;

    if (!email || !password) {
        showAlert('Заполни email и пароль');
        return;
    }

    const button = form.querySelector('button[type="submit"]');
    const { ok, data } = await postJson(button, '/api/login', { email, password });

    if (ok && data.redirect_url) {
        window.location.href = data.redirect_url;
        return;
    }
    showAlert(data.error || 'Не удалось войти, попробуй ещё раз');
}

async function handleRegister(form) {
    hideAlert();
    const name = form.querySelector('#fullname').value.trim();
    const email = form.querySelector('#email').value.trim();
    const password = form.querySelector('#password').value;
    const confirm = form.querySelector('#confirm_password').value;

    if (!name || !email || !password) {
        showAlert('Заполни все поля');
        return;
    }
    if (password.length < 6) {
        showAlert('Пароль должен быть не короче 6 символов');
        return;
    }
    if (password !== confirm) {
        showAlert('Пароли не совпадают');
        return;
    }

    const button = form.querySelector('button[type="submit"]');
    const { ok, data } = await postJson(button, '/api/register', { name, email, password });

    if (ok && data.redirect_url) {
        window.location.href = data.redirect_url;
        return;
    }
    showAlert(data.error || 'Не удалось зарегистрироваться');
}

// ---------- Баланс ----------

function setupTopup() {
    const amountInput = document.getElementById('topupAmount');
    const customButton = document.getElementById('topupCustom');

    document.querySelectorAll('.topup-btn').forEach((button) => {
        button.addEventListener('click', () => {
            const amount = Number(button.dataset.amount || 0);
            topUp(amount, button);
        });
    });

    if (customButton) {
        customButton.addEventListener('click', () => {
            const amount = Number(amountInput.value);
            if (!amount || amount < 10) {
                showAlert('Введи сумму от 10 ₽', 'topup-msg');
                return;
            }
            topUp(amount, customButton);
        });
    }

    if (amountInput) {
        amountInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                if (customButton) customButton.click();
            }
        });
    }
}

async function topUp(amount, button) {
    hideAlert('topup-msg');
    const { ok, data } = await postJson(button, '/api/topup', { amount });

    if (ok) {
        const balanceNode = document.getElementById('balanceAmount');
        if (balanceNode && data.balance) {
            balanceNode.textContent = data.balance;
        }
        showAlert(`Баланс пополнен на ${data.amount} ₽`, 'topup-msg', 'ok');
        const input = document.getElementById('topupAmount');
        if (input) input.value = '';
    } else {
        showAlert(data.error || 'Не удалось пополнить баланс', 'topup-msg');
    }
}

// ---------- Чат ----------

function setupChat() {
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const messages = document.getElementById('chat-messages');
    const clearButton = document.getElementById('chatClear');
    const badge = document.getElementById('modelBadge');

    // История нужна модели для контекста; живёт только в этой вкладке
    const history = [];
    let busy = false;

    function append(role, text, extraClass = '') {
        const node = document.createElement('div');
        node.className = `msg ${role}${extraClass ? ' ' + extraClass : ''}`;
        node.textContent = text;
        messages.appendChild(node);
        messages.scrollTop = messages.scrollHeight;
        return node;
    }

    function typing() {
        const node = document.createElement('div');
        node.className = 'msg bot typing';
        node.innerHTML = '<span></span><span></span><span></span>';
        messages.appendChild(node);
        messages.scrollTop = messages.scrollHeight;
        return node;
    }

    function setBadge(text, isOk) {
        if (!badge) return;
        badge.textContent = text;
        badge.classList.toggle('badge-ok', Boolean(isOk));
    }

    async function send() {
        const text = input.value.trim();
        if (!text || busy) return;

        busy = true;
        hideAlert();
        append('user', text);
        input.value = '';
        input.style.height = '';

        const bubble = typing();
        const payload = {
            message: text,
            history: history.slice(-10),
        };

        let response;
        try {
            response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        } catch (error) {
            bubble.remove();
            append('bot', 'Нет соединения с сервером. Проверь, что приложение запущено.', 'error');
            busy = false;
            return;
        }

        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = {};
        }

        bubble.remove();

        if (response.ok && data.reply) {
            append('bot', data.reply);
            history.push({ role: 'user', content: text });
            history.push({ role: 'assistant', content: data.reply });
            setBadge('модель загружена', true);
        } else {
            const message = data.error || 'Модель не ответила, попробуй ещё раз';
            append('bot', data.hint ? `${message}\n\n${data.hint}` : message, 'error');
            if (response.status === 202) {
                setBadge('модель загружается…', false);
            } else if (response.status === 503) {
                setBadge('модель не загружена', false);
            }
        }

        busy = false;
        input.focus();
    }

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        send();
    });

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            send();
        }
    });

    if (clearButton) {
        clearButton.addEventListener('click', () => {
            history.length = 0;
            messages.innerHTML = '';
            append('bot', 'Чат очищен. О чём поговорим?');
        });
    }

    // Узнаём состояние модели при открытии страницы
    fetch('/api/chat/status')
        .then((response) => (response.ok ? response.json() : null))
        .then((data) => {
            if (!data) return;
            if (data.demo) {
                setBadge('демо-режим без модели', true);
            } else if (data.ready) {
                setBadge('модель загружена', true);
            } else if (data.loading) {
                setBadge('модель загружается…', false);
            } else {
                setBadge('модель не загружена', false);
            }
        })
        .catch(() => {});
}
