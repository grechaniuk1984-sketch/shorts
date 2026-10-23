# YouTube Shorts: Crazy History Facts (10 відео)

## Запуск безкоштовно в хмарі (ПК і телефон можуть бути вимкнені)
1. Отримай безкоштовний ключ Pixabay: зареєструйся на pixabay.com, потім відкрий https://pixabay.com/api/docs/ — ключ буде в тексті сторінки (Pexels теж підтримується).
2. Створи репозиторій на GitHub (public = безлімітні хвилини) і завантаж туди всі файли цієї папки.
3. Repo → Settings → Secrets and variables → Actions → New secret:
   назва `PIXABAY_API_KEY`, значення — твій ключ.
4. Вкладка Actions → "Generate Shorts" → Run workflow.
5. Через ~10-20 хв у запуску з'явиться архів `shorts` (Artifacts) — там 10 mp4 і txt із назвою та описом для кожного.

## Музика (необов'язково)
Поклади royalty-free mp3 (напр. з YouTube Audio Library) у папку `music/`.

## Налаштування
- Голос: змінна `VOICE` (en-US-GuyNeural, en-US-AndrewNeural, en-GB-RyanNeural).
- Нові теми: додай записи в `scripts.json` (hook, script, keywords для пошуку відео).
- Локально: `pip install -r requirements.txt`, потрібен ffmpeg, далі `python make_videos.py`.
