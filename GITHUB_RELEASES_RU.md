# GitHub Releases — как публиковать обновления

Репозиторий:
https://github.com/popovnikitanorilsk77-lang/ArbitrageRadar

## Первый push

На компьютере откройте PowerShell в папке исходников:

```powershell
git init
git branch -M main
git remote add origin https://github.com/popovnikitanorilsk77-lang/ArbitrageRadar.git
git add .
git commit -m "Arbitrage Radar v0.5.2"
git push -u origin main
```

GitHub может открыть окно авторизации. Пароль/токен в ChatGPT передавать не нужно.

## Каждый новый релиз

1. Создать ZIP релиза.
2. На GitHub открыть Releases → Draft a new release.
3. Tag: например `v0.6.0`.
4. Прикрепить ZIP.
5. Скопировать прямой URL ZIP.
6. Обновить `update.json` в ветке main:
   - version
   - zip_url
   - sha256
   - notes
7. Commit update.json.

Приложение читает:
https://raw.githubusercontent.com/popovnikitanorilsk77-lang/ArbitrageRadar/main/update.json

и по кнопке «Проверить обновления онлайн»:
- сравнивает версии;
- скачивает ZIP;
- проверяет SHA-256;
- делает backup;
- устанавливает;
- перезапускается.
