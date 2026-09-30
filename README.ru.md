# ExaBGP + Python route fetcher lab

Лабораторный стенд: загрузка списков IPv4 CIDR из HTTP(S), валидация,
назначение BGP standard communities по источникам, объединение
дублирующихся префиксов и анонс/отзыв маршрутов через ExaBGP.

Полная документация (на английском): [README.md](README.md)

## Архитектура

raw URLs -> Python fetcher -> ExaBGP -> ваш BGP-маршрутизатор

Конфигурация маршрутизатора в проект не входит.

## Значения по умолчанию

- Адрес ExaBGP: `192.168.80.10`
- AS ExaBGP: `65001`
- BGP-сосед: `192.168.80.1`
- AS соседа: `65000`
- IPv4 unicast
- refresh: 300 секунд
- суммарный лимит: 10 000 префиксов

Редактируйте `config/exabgp.conf` для BGP-соседа и `config/sources.json`
для источников/сообществ.

## Типы источников

Каждый источник имеет `type`:

### URL

```json
{
  "name": "github-list",
  "type": "url",
  "url": "https://raw.githubusercontent.com/ORG/REPO/main/routes.txt",
  "communities": ["65001:100", "no-export"]
}
```

### Локальный файл

Compose-файл монтирует `./lists` в режиме только чтения как
`/etc/exabgp/lists`.

```json
{
  "name": "local-list",
  "type": "file",
  "path": "/etc/exabgp/lists/local.txt",
  "communities": ["65001:200"]
}
```

Локальный файл использует тот же формат, что и URL-списки: один IPv4 CIDR
на строку, пустые строки и комментарии `#` допускаются.

### ASN

ASN-источники используют REST API RIPEstat `announced-prefixes`. RIPE NCC
документирует этот endpoint как возвращающий анонсированные префиксы для
заданного ASN и поддерживает `min_peers_seeing` для исключения
низковидимых анонсов.

```json
{
  "name": "google",
  "type": "asn",
  "asn": 15169,
  "min_peers_seeing": 10,
  "max_prefixes": 5000,
  "communities": ["65001:300", "no-export"]
}
```

Ответ RIPEstat нормализуется через те же проверки CIDR и лимиты длины
префикса, что и URL/локальные источники.

ASN-источник означает **префиксы, наблюдаемые как анонсируемые этим ASN**,
а не адресное пространство RIR, зарегистрированное на этот ASN. Это данные
наблюдения за маршрутизацией и могут меняться со временем.

Можно настроить несколько ASN как отдельные источники, у каждого свой
набор сообществ.

Пример:

```json
"sources": [
  {
    "name": "asn-15169",
    "type": "asn",
    "asn": 15169,
    "communities": ["65001:300", "no-export"]
  },
  {
    "name": "asn-13335",
    "type": "asn",
    "asn": 13335,
    "communities": ["65001:301"]
  }
]
```

Для ASN-источников `min_peers_seeing` по умолчанию берётся из глобальной
настройки `asn_min_peers_seeing` (в примере 10).

## Модель сообществ

Каждый источник имеет массив `communities`:

```json
{
  "name": "malware",
  "url": "https://raw.githubusercontent.com/example/project/main/list.txt",
  "max_prefixes": 5000,
  "communities": [
    "65001:100",
    "no-export"
  ]
}
```

Поддерживаемые стандартные сообщества в этом стенде:

- `ASN:value`, например `65001:100`
- `internet`
- `no-export`
- `no-advertise`
- `no-export-subconfed`

Если один и тот же префикс встречается в нескольких источниках,
сообщества объединяются (UNION).

Пример:

источник A:
`10.0.0.0/24 -> 65001:100`

источник B:
`10.0.0.0/24 -> 65001:200 no-export`

Итоговый анонс содержит:

`65001:100 65001:200 no-export`

Если набор сообществ префикса изменился, fetcher отзывает старый путь и
повторно анонсирует его с новыми атрибутами.

## Агрегация

Любой источник (`url`, `file` или `asn`) может задать необязательный объект
`aggregate`. Он выполняется после парсинга и до проверок
`max_prefixes` / `max_total_prefixes`, поэтому большой фид можно свести
под лимит вместо отклонения.

Два режима:

```json
{
  "name": "hourly-threat-ipv4",
  "type": "url",
  "url": "https://raw.githubusercontent.com/example/feed/main/hourlyIPv4.txt",
  "max_prefixes": 150000,
  "communities": ["65001:100", "no-export"],
  "aggregate": { "mode": "safe" }
}
```

`"mode": "safe"` без потерь объединяет только строго смежные префиксы
(не анонсируется адрес, которого не было в источнике). Сокращение
полностью зависит от того, насколько смежными оказались адреса фида.

```json
{
  "name": "hourly-threat-ipv4",
  "type": "url",
  "url": "https://raw.githubusercontent.com/example/feed/main/hourlyIPv4.txt",
  "max_prefixes": 100000,
  "communities": ["65001:100", "no-export"],
  "aggregate": { "mode": "threshold", "prefix_len": 24, "threshold": 8 }
}
```

`"mode": "threshold"` схлопывает любую сеть `/prefix_len`, содержащую
`>= threshold` префиксов из этого источника, в один супернет.
**Это анонсирует адреса, которых не было в источнике** (все остальные
хосты этой сети) — используйте только там, где такой риск ложных
срабатываний приемлем, например в RTBH-фидах, где лучше перекрыть
шумную подсеть, чем анонсировать десятки тысяч отдельных `/32`.

Источник без ключа `aggregate` работает как раньше.

## Поведение при сбоях (fail closed)

Fetcher намеренно закрывается в безопасном состоянии:

- невалидные CIDR игнорируются;
- IPv6 по умолчанию игнорируется;
- лимиты длины префикса соблюдаются;
- лимиты на источник соблюдаются;
- суммарный лимит префиксов соблюдается;
- HTTP-ошибка не отзывает ранее успешный источник;
- пустой источник считается сбойным и не отзывает своё старое состояние;
- если все источники сбойны, состояние не меняется.

Это консервативное поведение. Если нужен сценарий «источник исчез =>
отозвать все его маршруты», реализуйте это как явную политику, а не
трактуйте каждую HTTP-ошибку как пустой список.

## Важно

`network_mode: host` используется намеренно. ExaBGP должен устанавливать
TCP/179 к вашему BGP-маршрутизатору без проблем Docker port/NAT.

Не открывайте TCP/179 для недоверенных сетей. Используйте файрвол хоста
и разрешайте только нужных BGP-соседей.

## Установка бинарника ExaBGP (без Docker)

Готовые бинарники публикуются автоматически при каждом пуше тега.
Страница GitHub Release содержит архив с последней версией.

### Через скрипт установки (рекомендуется)

```bash
# Установить последний релиз
curl -fsSL https://github.com/netcorexc0a8/exabgp/releases/latest/download/install.sh | sudo sh

# Или установить конкретную версию
curl -fsSLO https://github.com/netcorexc0a8/exabgp/releases/latest/download/install.sh
sudo sh install.sh v5.0.3
```

Скрипт автоматически определяет архитектуру (amd64, arm64, 386) и,
если версия не указана, резолвит последний тег релиза.

### Ручная установка

Готовые бинарники доступны на странице релизов ExaBGP на GitHub:

```bash
# Замените VERSION на нужный релиз, например 5.0.3
VERSION=5.0.3

# Скачивание и установка
curl -L "https://github.com/exabgp/exabgp/releases/download/v${VERSION}/exabgp_${VERSION}_linux_amd64.tar.gz" \
    -o /tmp/exabgp.tar.gz
tar -xzf /tmp/exabgp.tar.gz -C /tmp
sudo cp /tmp/exabgp /usr/local/bin/exabgp
sudo chmod +x /usr/local/bin/exabgp

# Проверка
exabgp --version
```

### Debian/Ubuntu

```bash
VERSION=5.0.3
wget "https://github.com/exabgp/exabgp/releases/download/v${VERSION}/exabgp_${VERSION}_linux_amd64.tar.gz" -O /tmp/exabgp.tar.gz
tar -xzf /tmp/exabgp.tar.gz -C /tmp
sudo cp /tmp/exabgp /usr/local/bin/exabgp
```

### Создание пользователя exabgp

```bash
sudo useradd --system --uid 10001 --create-home exabgp
```

### Создание именованных каналов (named pipes)

CLI-режиму ExaBGP требуются именованные каналы:

```bash
sudo mkdir -p /opt/fetcher/run
sudo mkfifo /opt/fetcher/run/exabgp.in
sudo mkfifo /opt/fetcher/run/exabgp.out
sudo chown -R exabgp:exabgp /opt/fetcher/run
sudo chmod 600 /opt/fetcher/run/exabgp.in /opt/fetcher/run/exabgp.out
```

### Настройка

Разместите файлы:

```bash
sudo mkdir -p /etc/exabgp
sudo cp config/exabgp.conf /etc/exabgp/exabgp.conf
sudo cp config/sources.json /etc/exabgp/sources.json
sudo cp fetcher/fetcher.py /opt/fetcher/fetcher.py
sudo chown -R exabgp:exabgp /etc/exabgp /opt/fetcher
```

### Запуск

```bash
sudo -u exabgp exabgp /etc/exabgp/exabgp.conf
```

Или как systemd-сервис (необязательно):

```bash
sudo cp exabgp.service /etc/systemd/system/exabgp.service
sudo systemctl daemon-reload
sudo systemctl enable --now exabgp
```

## Docker-образ

Готовый Docker-образ автоматически собирается при каждом пуше в `main`
и при каждом теге. Образ публикуется в GitHub Container Registry (GHCR).

### Предварительные требования

Перед загрузкой образа создайте необходимые директории и файлы
конфигурации. Контейнер монтирует эти пути во время выполнения:

```bash
mkdir -p config fetcher lists state
```

Создайте или отредактируйте файлы конфигурации:

```bash
# Отредактируйте под ваш BGP-сетап
# config/exabgp.conf - BGP-сосед, локальный AS, таймеры
# config/sources.json - источники, сообщества, настройки
# fetcher/fetcher.py - Python-скрипт fetcher
```

Если нужны локальные списки префиксов, положите их в `lists/`:

```bash
# Пример: один IPv4 CIDR на строку, пустые строки и # комментарии
echo "203.0.113.0/24" > lists/local.txt
```

Директория `state/` сохраняет состояние ExaBGP между перезапусками.

Образ заранее создаёт директорию `run/` и именованные каналы FIFO
(`exabgp.in`, `exabgp.out`), необходимые CLI-режиму ExaBGP. Действий
не требуется.

### Загрузка последнего образа

```bash
docker pull ghcr.io/netcorexc0a8/exabgp:latest
```

### Запуск через docker compose

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

Переопределите образ в `docker-compose.yml`:

```yaml
services:
  exabgp:
    image: ghcr.io/netcorexc0a8/exabgp:latest
    container_name: exabgp
    restart: unless-stopped
    network_mode: host
    environment:
      EXABGP_LOG_ALL: "true"
      PYTHONUNBUFFERED: "1"
    volumes:
      - ./config/exabgp.conf:/etc/exabgp/exabgp.conf:ro
      - ./config/sources.json:/etc/exabgp/sources.json:ro
      - ./fetcher/fetcher.py:/opt/fetcher/fetcher.py:ro
      - ./lists:/etc/exabgp/lists:ro
      - ./state:/var/lib/exabgp
    command: ["exabgp", "/etc/exabgp/exabgp.conf"]
```

Или укажите образ через командную строку без правки файла:

```bash
docker compose up -d --build
```

Чтобы использовать конкретный тег, замените `latest` на нужный
(например `v1.0.0` или `sha-a1b2c3d`).

### Запуск через docker run

```bash
docker run -d \
  --name exabgp \
  --network host \
  -v "$(pwd)/config/exabgp.conf:/etc/exabgp/exabgp.conf:ro" \
  -v "$(pwd)/config/sources.json:/etc/exabgp/sources.json:ro" \
  -v "$(pwd)/fetcher/fetcher.py:/opt/fetcher/fetcher.py:ro" \
  -v "$(pwd)/lists:/etc/exabgp/lists:ro" \
  -v "$(pwd)/state:/var/lib/exabgp" \
  ghcr.io/netcorexc0a8/exabgp:latest
```

### Workflow сборки

Сборка описана в `.github/workflows/build-image.yml`. Триггеры:

- каждый пуш в `main`
- каждый тег вида `v*`
- ручной запуск через Actions UI

Workflow собирает образ через Docker Buildx, публикует в GHCR и тегирует:

- `latest` — при пушах в `main`
- `sha-<short-sha>` — при каждом пуше
- имя тега — при пушах тегов (например `v1.0.0`)

Workflow использует стандартный секрет `GITHUB_TOKEN`, дополнительная
настройка не требуется. Если образ нужен из приватного репозитория,
убедитесь, что разрешение `packages: write` выдано (оно задано в файле
workflow).

## Версия

Dockerfile фиксирует ExaBGP `5.0.3` для воспроизводимости. Измените
`EXABGP_VERSION` после проверки более новой версии.
