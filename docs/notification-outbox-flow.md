# Как работают TG-уведомления через outbox

Визуальная схема transactional outbox: бизнес-изменение и intent уведомления
коммитятся вместе; Telegram вызывается отдельным worker'ом.


---

## Два пути: запрос и worker

```mermaid
flowchart TB
    subgraph request [Request path — в одной транзакции с бизнесом]
        DS[Domain service<br/>payment_service · order_service · support]
        NS[Notification service<br/>customer / admin / support]
        OD[OutboxNotificationDispatcher.enqueue]
        OB[(notification_outbox<br/>status = pending)]
        BIZ[(orders · payments · support_messages)]
        DS --> NS
        NS --> OD
        OD --> OB
        DS --> BIZ
        BIZ --- OB
        COMMIT{{COMMIT}}
        BIZ --> COMMIT
        OB --> COMMIT
    end

    subgraph worker [Worker path — cron каждую минуту]
        JOB[notification_outbox_job<br/>make notification-outbox]
        CLAIM[claim_pending_batch<br/>FOR UPDATE SKIP LOCKED]
        DLV[inline_dispatcher.deliver]
        CMP[composer + content/*]
        TG[telegram_client]
        SENT[mark_sent]
        FAIL[mark_failed / retry]
        JOB --> CLAIM
        CLAIM --> DLV
        DLV --> CMP
        CMP --> TG
        DLV --> SENT
        DLV --> FAIL
    end

    COMMIT -.->|строки pending| CLAIM
    TG -->|ok| SENT
    TG -->|fail| FAIL
    FAIL -.->|до 5 попыток, backoff| CLAIM
```

**Prod:** `NOTIFICATION_MODE=outbox` — в HTTP/callback пути нет вызова Telegram.
**Local debug:** `NOTIFICATION_INLINE=1` — сразу `deliver()`, без записи в outbox.

---

## Пример: callback SBP «оплата принята» (обычный путь)

Один `COMMIT` фиксирует и статус оплаты, и две строки outbox (админ + клиент).

```mermaid
sequenceDiagram
    participant K as SBP callback
    participant PS as payment_service
    participant DB as Postgres
    participant OB as notification_outbox
    participant CRON as notification_outbox_job
    participant TG as Telegram

    K->>PS: handle_sbp_callback(IPS_ACCEPTED)
    PS->>DB: UPDATE order / payment_attempt (paid)
    PS->>PS: _schedule_payment_notifications()
    PS->>OB: INSERT admin:payment.accepted (pending)
    PS->>OB: INSERT customer:payment.received (pending)
    PS->>DB: COMMIT

    Note over OB: при email в notification_channels —<br/>вторая строка customer:payment.received:…:email

    Note over CRON: через ≤1 мин (cron */1)
    CRON->>OB: claim batch (SKIP LOCKED)
    CRON->>TG: deliver(admin payment.accepted)
    TG-->>CRON: ok
    CRON->>OB: status = sent
    CRON->>TG: deliver(customer payment.received)
    TG-->>CRON: ok
    CRON->>OB: status = sent
    CRON->>DB: order_event (после успешного TG/email)
```

## Пример: late payment (`status == cancelled`)

Заказ уже отменён, пришла первая успешная оплата. Клиенту **не** шлётся `payment.received`
(ни TG, ни email).

```mermaid
sequenceDiagram
    participant PS as payment_service
    participant OB as notification_outbox

    PS->>PS: _mark_attempt_accepted → LateNotify
    PS->>OB: INSERT admin:payment.late:order:{id}:attempt:{aid}
    PS->>OB: INSERT customer:payment.late.received:order:{id}:attempt:{aid}:telegram
    Note over OB: при email в channels —<br/>+ customer:payment.late.received:…:email
```

Текст для email — тот же `payment.late.received`, формат plain (`compose_email_notification`).

Journey payment stage учитывает оба шаблона: `payment.received` и `payment.late.received`
(TG и Email по `customer_notified`).

## Пример: duplicate payment (вторая успешная попытка)

Заказ уже оплачен другой попыткой. Клиенту **ничего**; админу критический TG.

```mermaid
sequenceDiagram
    participant PS as payment_service
    participant OB as notification_outbox

    PS->>PS: _mark_attempt_accepted → DuplicatePaymentNotify
    PS->>OB: INSERT admin:payment.duplicate:order:{id}:attempt:{aid}
```

Idempotency per attempt: повторный callback той же попытки не создаёт вторую строку
(`mark_payment_attempt_paid_if_unpaid` + `UNIQUE(idempotency_key)`).

**Dedup:** повторный callback с тем же событием → `UNIQUE(idempotency_key)` не даёт
вторую строку outbox.

---

## Жизненный цикл строки outbox

```mermaid
stateDiagram-v2
    [*] --> pending: enqueue в txn домена

    pending --> processing: worker claim<br/>FOR UPDATE SKIP LOCKED
    processing --> sent: deliver ok
    processing --> pending: TG fail, attempts < 5<br/>backoff на locked_at
    processing --> failed: attempts = 5<br/>или terminal error
    processing --> pending: reset_stuck_processing<br/>зависла > 5 мин

    sent --> [*]
    failed --> [*]
```

| Статус | Кто меняет | Смысл |
|--------|------------|-------|
| `pending` | domain insert / retry | ждёт worker |
| `processing` | worker claim | доставка в процессе |
| `sent` | worker | TG доставлен |
| `failed` | worker | исчерпаны попытки |

---

## Если outbox не записался — откат всей транзакции

Scheduling уведомления не оборачивается в `try/except`: сбой INSERT в outbox
отменяет и изменение оплаты.

```mermaid
sequenceDiagram
    participant PS as payment_service
    participant DB as Postgres
    participant OB as notification_outbox

    PS->>DB: UPDATE order → paid (в сессии)
    PS->>OB: INSERT admin (ok)
    PS->>OB: INSERT customer (ошибка)
    PS--xDB: COMMIT не вызывается
    Note over DB: rollback — оплата не сохранена,<br/>строк outbox нет
```

---

## Несколько worker'ов — без двойной доставки

```mermaid
sequenceDiagram
    participant W1 as worker A
    participant W2 as worker B
    participant OB as notification_outbox row #42

    W1->>OB: SELECT … FOR UPDATE
    Note over OB: row заблокирована
    W2->>OB: SELECT … FOR UPDATE SKIP LOCKED
    Note over W2: строка пропущена
    W1->>OB: deliver → sent
    W1->>OB: COMMIT
```

Параллельные cron-запуски или два инстанса API не шлют одно и то же сообщение дважды:
каждая строка забирается одним worker'ом.

---

## Что проверяем тестами

| Сценарий | Где |
|----------|-----|
| dedup по `idempotency_key` | `tests/integration/test_notification_outbox.py` |
| `SKIP LOCKED` при параллельном claim | там же |
| `handle_sbp_callback` → оплата + 2 outbox (обычный путь) | там же |
| late payment → `payment.late` + `payment.late.received` | `tests/unit/test_unpaid_order_lifecycle.py` |
| duplicate → `payment.duplicate` admin only | `tests/unit/test_payment_attempts.py` |
| сбой outbox → rollback оплаты | `tests/integration/test_notification_outbox.py` |
| 5 retry → `failed` | там же |

```bash
make test-integration   # PostgreSQL
make notification-outbox   # ручной прогон worker локально
```
