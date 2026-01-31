# NUM Assistant (Unified Rasa Backend)

Энэ төсөл нь дараах модулиудыг нэгтгэсэн нэг Rasa backend юм:
- Сургалтын төлбөр тооцоолол
- GPA (голч) тооцоолол
- МУИС байр, төвүүдийн байршил
- Албан бичгийн загварууд (чөлөө, өвчтэй, дүн асуух, W/I)

## Шаардлага

- Python 3.10+
- Rasa + rasa-sdk
- Git (repo татахад)

> Хэрвээ `requirements.txt` байхгүй бол:
```bash
pip install rasa rasa-sdk
```

## GitHub-оос суулгах (шинэ laptop/computer дээр)

### 1) Repo татах
```bash
git clone https://github.com/ganerdenemargaderdene-dotcom/NUM_assistant.git
cd NUM_assistant
```

### 2) Виртуал орчин үүсгээд идэвхжүүлэх

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3) Хамаарал суулгах

Хэрвээ `requirements.txt` байвал:
```bash
pip install -r requirements.txt
```

Хэрвээ байхгүй бол:
```bash
pip install rasa rasa-sdk
```

## Ажиллуулах

1) Виртуал орчноо идэвхжүүлнэ (Windows/Powershell):

```powershell
.\.venv\Scripts\Activate.ps1
```

2) Моделио сургана:

```bash
rasa train
```

3) Action server асаана:

```bash
rasa run actions
```

4) Rasa server асаана:

```bash
rasa run --enable-api --cors "*"
```

## Тест хийх жишээ

### PowerShell дээр (UTF-8 зөв)
```powershell
Invoke-WebRequest -Uri "http://localhost:5005/webhooks/rest/webhook" `
  -Method POST `
  -Headers @{ "Content-Type" = "application/json; charset=utf-8" } `
  -Body (@{ sender="test"; message="төлбөр бодоорой" } | ConvertTo-Json)
```

### curl.exe ашиглах
```powershell
curl.exe -X POST http://localhost:5005/webhooks/rest/webhook `
  -H "Content-Type: application/json" `
  -d "{\"sender\":\"test\",\"message\":\"төлбөр бодоорой\"}"
```

## Файл бүтэц

- `data/` - training data (`nlu.yml`, `rules.yml`)
- `models/` - сурсан model файлууд
- `actions.py` - custom actions
- `domain.yml` - intents, slots, responses, forms

## Түгээмэл асуудал

- `Failed to run custom action ... http://localhost:5055/webhook`  
  Action server асаагүй байна. `rasa run actions` ажиллаж байгаа эсэхийг шалга.


  -Маргад-Эрдэнэ, Маралжингоо, Азжаргал, Цэлмэг-


## UI (HTML)

`index.html` ???? ?? Rasa REST webhook ??? ?????????? ??? ???? UI ??.

### ???????
1) Rasa action server ??????:
```bash
rasa run actions
```
2) Rasa server ??????:
```bash
rasa run --enable-api --cors "*"
```
3) `index.html`-??? ??????? ????????.

### RASA_URL ???????
`index.html` ?????? ???? ?????? ??????:
```js
const RASA_URL = "http://localhost:5005/webhooks/rest/webhook";
```
?????? ?????? ????????? ????/???? ??? ??????????.
