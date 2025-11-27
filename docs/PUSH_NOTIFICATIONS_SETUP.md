# Руководство по настройке push-уведомлений

Это руководство объясняет, как завершить настройку push-уведомлений для Speakr.

## Обзор

Инфраструктура push-уведомлений на стороне клиента теперь завершена. Чтобы включить push-уведомления, вам нужно:

1. Сгенерировать VAPID ключи
2. Настроить клиент с публичным ключом
3. Реализовать бэкенд-эндпоинты для хранения подписок и отправки уведомлений

## Шаг 1: Генерация VAPID ключей

### Метод A: Использование web-push (Node.js)

```bash
npm install -g web-push
web-push generate-vapid-keys
```

### Метод B: Использование Python

```bash
pip install pywebpush
```

```python
from pywebpush import vapid_keys

vapid_keys = vapid_keys()
print("Public Key:", vapid_keys['publicKey'])
print("Private Key:", vapid_keys['privateKey'])
```

### Метод C: Использование pywebpush CLI

```bash
pywebpush generate-vapid-keys
```

**ВАЖНО:** Держите приватный ключ в секрете! Никогда не коммитьте его в систему контроля версий.

## Шаг 2: Настройка клиента

1. Откройте `static/js/config/push-config.js`
2. Установите `ENABLED: true`
3. Добавьте ваш VAPID публичный ключ в `VAPID_PUBLIC_KEY`
4. Обновите `CONTACT_INFO` с вашей административной электронной почтой или веб-сайтом

```javascript
export const PUSH_CONFIG = {
    ENABLED: true,
    VAPID_PUBLIC_KEY: 'YOUR_PUBLIC_KEY_HERE',
    CONTACT_INFO: 'mailto:admin@yourdomain.com'
};
```

## Шаг 3: Реализация бэкенд-эндпоинтов

### Необходимые бэкенд-эндпоинты

#### 1. Сохранение push-подписки

**Эндпоинт:** `POST /api/push/subscribe`

**Назначение:** Сохранить push-подписку пользователя в базе данных

**Тело запроса:**
```json
{
    "endpoint": "https://fcm.googleapis.com/fcm/send/...",
    "keys": {
        "p256dh": "...",
        "auth": "..."
    }
}
```

**Ответ:**
```json
{
    "success": true,
    "message": "Subscription saved"
}
```

**Пример реализации (Flask):**

```python
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from models import db, PushSubscription

push_bp = Blueprint('push', __name__)

@push_bp.route('/api/push/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Store push subscription for current user"""
    subscription_data = request.json

    # Check if subscription already exists
    existing = PushSubscription.query.filter_by(
        user_id=current_user.id,
        endpoint=subscription_data['endpoint']
    ).first()

    if existing:
        return jsonify({'success': True, 'message': 'Already subscribed'})

    # Create new subscription
    subscription = PushSubscription(
        user_id=current_user.id,
        endpoint=subscription_data['endpoint'],
        p256dh_key=subscription_data['keys']['p256dh'],
        auth_key=subscription_data['keys']['auth']
    )

    db.session.add(subscription)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Subscription saved'})
```

#### 2. Удаление push-подписки

**Эндпоинт:** `POST /api/push/unsubscribe`

**Назначение:** Удалить push-подписку пользователя из базы данных

**Тело запроса:** То же, что и для subscribe

**Ответ:**
```json
{
    "success": true,
    "message": "Subscription removed"
}
```

**Пример реализации:**

```python
@push_bp.route('/api/push/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    """Remove push subscription for current user"""
    subscription_data = request.json

    subscription = PushSubscription.query.filter_by(
        user_id=current_user.id,
        endpoint=subscription_data['endpoint']
    ).first()

    if subscription:
        db.session.delete(subscription)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Subscription removed'})

    return jsonify({'success': False, 'message': 'Subscription not found'}), 404
```

## Шаг 4: Модель базы данных

Добавьте модель `PushSubscription` в вашу базу данных:

```python
from models import db
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func

class PushSubscription(db.Model):
    __tablename__ = 'push_subscriptions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    endpoint = Column(String(500), nullable=False, unique=True)
    p256dh_key = Column(String(200), nullable=False)
    auth_key = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        db.Index('idx_user_endpoint', 'user_id', 'endpoint'),
    )
```

Создайте миграцию:

```bash
flask db migrate -m "Add push subscriptions table"
flask db upgrade
```

## Шаг 5: Отправка push-уведомлений

Используйте библиотеку `pywebpush` для отправки уведомлений, когда транскрибация завершена:

```python
from pywebpush import webpush, WebPushException
import json
import os

def send_push_notification(user_id, title, body, data=None):
    """Send push notification to all subscriptions for a user"""
    subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()

    vapid_private_key = os.getenv('VAPID_PRIVATE_KEY')
    vapid_contact = os.getenv('VAPID_CONTACT', 'mailto:admin@example.com')

    notification_data = {
        'title': title,
        'body': body,
        'icon': '/static/img/icon-192x192.png',
        'badge': '/static/img/icon-192x192.png',
        'data': data or {}
    }

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {
                        'p256dh': subscription.p256dh_key,
                        'auth': subscription.auth_key
                    }
                },
                data=json.dumps(notification_data),
                vapid_private_key=vapid_private_key,
                vapid_claims={'sub': vapid_contact}
            )
            print(f'Push notification sent to user {user_id}')
        except WebPushException as e:
            print(f'Failed to send push to {subscription.endpoint}: {e}')
            # If subscription is expired, remove it
            if e.response and e.response.status_code in [404, 410]:
                db.session.delete(subscription)
                db.session.commit()
```

## Шаг 6: Интеграция с транскрибацией

Вызовите функцию push-уведомления, когда транскрибация завершена:

```python
# In your transcription completion handler
def on_transcription_complete(recording_id):
    recording = AudioFile.query.get(recording_id)

    if recording:
        send_push_notification(
            user_id=recording.user_id,
            title='Transcription Complete',
            body=f'"{recording.display_name or recording.filename}" has been transcribed',
            data={
                'recording_id': recording_id,
                'url': f'/recording/{recording_id}'
            }
        )
```

## Шаг 7: Переменные окружения

Добавьте эти переменные окружения в ваш файл `.env`:

```bash
# VAPID keys for push notifications
VAPID_PRIVATE_KEY=your_private_key_here
VAPID_CONTACT=mailto:admin@yourdomain.com
```

## Тестирование push-уведомлений

1. Откройте приложение в браузере
2. Откройте Developer Tools > Console
3. Выполните: `await pwaComposable.subscribeToPushNotifications()`
4. Проверьте базу данных, чтобы убедиться, что подписка была сохранена
5. Запустите тестовое уведомление с бэкенда
6. Убедитесь, что уведомление появилось

## Поддержка браузеров

| Браузер | Desktop | Mobile |
|---------|---------|--------|
| Chrome  | ✅      | ✅     |
| Edge    | ✅      | ✅     |
| Firefox | ✅      | ✅     |
| Safari  | ✅      | ⚠️ iOS 16.4+ |
| Opera   | ✅      | ✅     |

**Примечание:** iOS Safari требует iOS 16.4+ и приложение должно быть добавлено на главный экран.

## Решение проблем

### Подписка терпит неудачу с "NotAllowedError"
- Пользователь отклонил разрешение на уведомления
- Попросите пользователя включить уведомления в настройках браузера

### Подписка не сохраняется на сервере
- Проверьте, что бэкенд-эндпоинт доступен
- Проверьте, что CSRF токен действителен
- Проверьте логи сервера на ошибки

### Push-уведомления не получены
- Проверьте, что VAPID ключи совпадают между клиентом и сервером
- Проверьте, что подписка есть в базе данных
- Протестируйте с инструментами разработчика браузера
- Убедитесь, что service worker зарегистрирован

## Соображения безопасности

1. **Никогда не раскрывайте приватный VAPID ключ** - Держите его только на сервере
2. **Проверяйте подписки** - Убедитесь, что они принадлежат аутентифицированным пользователям
3. **Ограничивайте частоту подписок** - Предотвращайте злоупотребления
4. **Очищайте истекшие подписки** - Удаляйте ответы 404/410
5. **Используйте HTTPS** - Требуется для push-уведомлений

## Дополнительные ресурсы

- [Web Push Protocol](https://datatracker.ietf.org/doc/html/rfc8030)
- [VAPID Specification](https://datatracker.ietf.org/doc/html/rfc8292)
- [pywebpush Documentation](https://github.com/web-push-libs/pywebpush)
- [MDN Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
