# Формат связанных доказательств

Это локальный протокол входа, а не внешний сертификат и не разрешение на торговлю.

В `channel_input_v1` добавляется необязательное поле:

```json
{
  "research_evidence": {
    "relative_strength": {"path": "evidence/model.json", "sha256": "<SHA256 bytes>"}
  }
}
```

Поле входит в общий `manifest_hash`. Неизвестный id модели или явный null запрещены.
Без поля старый manifest читается, но идентичность/сертификация считаются неизвестными.

Файл модели содержит обязательные поля:

- `schema`: `channel_research_evidence_v1`.
- `plan_hash`, `model_hash`: точные значения неизменённого плана.
- `runtime_hash`: `canonical_hash(runtime_binding())` проверяемого кода.
- `dataset_binding_hash`: `dataset_binding(selected)`, где selected соответствует
  `runner.model_inputs`. Хэш включает все поля entry, включая SHA256 данных,
  отсортированные по id; число строк само по себе недостаточно.
- `identities`: список записей ниже, допустим пустой.
- `certificates`: список максимум из одного exposure и одного execution, допустим пустой.

Не требуется циклическая привязка к manifest_hash: manifest связывает файл модели,
а файл модели связывает точный набор entry и их SHA256.

Запись identities:

```json
{
  "symbol": "XAUUSD",
  "economic_base_id": "commodity:gold",
  "identity_key": "gold",
  "valid_from": "2023-01-01T00:00:00Z",
  "valid_to": "2023-02-01T00:00:00Z",
  "available_at": "2023-01-01T00:00:00Z",
  "evidence_refs": [{"path": "evidence/dated-source.txt", "sha256": "<SHA256 bytes>"}]
}
```

Это пример структуры, не реальные доказательства. Интервал `[valid_from, valid_to)`
должен целиком покрывать сделку, `available_at <= entry_ts`. Записи не сшиваются
автоматически поверх позиции. Symbol обозначает выходной символ адаптера в области
одной модели и связанных datasets; неоднозначность между площадками не разрешается
угадыванием. Опционные записи описывают underlying BTC/ETH, а не отдельный контракт.

Запись certificates: kind (`exposure`/`execution`), claim
(`UNSEEN_CERTIFIED`/`EXECUTABLE_CERTIFIED` соответственно), точный объект periods
из плана, непустые reviewer, method и evidence_refs. Результат чтения всегда
`BOUND_NOT_INDEPENDENTLY_CERTIFIED`, оба certification-флага false.

Все пути относительно каталога input manifest, включая evidence_refs внутри вложенного
файла. Только локальные файлы: без абсолютных путей, URL, `..`, alternate data streams
или выхода через symlink. Проверяются точные байты, включая повторное чтение в конце.
Дубли JSON-ключей, NaN/Infinity, пустые доказательства и противоречивые хэши запрещены.

Ограничения одного пакета: 1 MiB на файл, 16 MiB уникальных файлов, 64 ссылки/файла,
10 000 записей identities. Один и тот же путь не перечитывается для каждой записи,
но его байты повторно сверяются в конце. Общий runtime остаётся ограниченным launcher.
Пакет не скачивает сеть, не изменяет исходники и не создаёт output при validate.

Receipt содержит `evidence_hash`, список файлов и их размеров/SHA256, привязки,
нормализованные интервалы и явно отрицательные флаги независимой сертификации.
Внутренний receipt не следует принимать от внешнего вызывающего кода вместо
`load_evidence`; runner всегда строит его заново из проверенных входов.
