# Восстановление Renoir

Репозиторий приватный. Нужны Git, GitHub CLI, Python 3.12+, Linux/WSL и около 20 ГБ свободного места. Сначала выполни `gh auth login`.

```sh
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git darwin-renoir
cd darwin-renoir
python3 recovery/restore.py --build-inputs
```

Скрипт скачивает семь assets релиза `renoir-recovery-20261022`, проверяет SHA256 и восстанавливает packfs-образы, native-прошивки Renoir и сборочные инструменты. Пароль Wi-Fi, SSH-ключи и токены доступа исключены. Сеть нужно выбрать и настроить в iOS. MAC этого телефона сохранён в загрузочных параметрах: он нужен драйверу.

Переведи телефон в штатный fastboot и запусти:

```sh
python3 recovery/boot.py
```

Сохранён и предыдущий проверенный на телефоне вариант ядра/root до обновления служб. Если новый вариант не подходит, запусти `python3 recovery/boot.py --last-phone-good`. У него тоже удалён пароль Wi-Fi; это резервный payload, а не обещание новой аппаратной проверки.

Нужны platform-tools. Поддерживается Windows fastboot.exe из C:/platform-tools через WSL. Скрипт проверяет модель, выполняет fastboot boot и загружает образы исключительно в RAM. Уже работающий xnuloader сначала перезапусти в штатный fastboot. После обычной перезагрузки возвращается Android; изменения внутри RAM-iOS не сохраняются.

## Исходники UEFI

Из корня ядра:

```sh
git clone --branch silicium-renoir --single-branch --recursive https://github.com/wannqn/darwin-renoir.git Mu-Silicium
python3 Mu-Silicium/Recovery/prepare.py
```

prepare.py восстанавливает локальный патч Mu_Basecore. Без этого один clone --recursive не возвращает все изменения. Готовый загрузчик уже сохранён в prebuilt/renoir; для обычного запуска пересборка UEFI не нужна. Экспериментальный патч 90 Гц не включён, сохранён отдельно.

## Пересборка

Архив build-inputs содержит Theos SDK/toolchain, зависимости XNU и QEMU; абсолютные symlink SDK перепривязываются к новой папке. Системные Linux-пакеты нужны заново: clang, lld, llvm, make, cc/c++, git, curl, Python, 7z, flex, bison, autoconf, automake, nasm, pkg-config. Используй Linux-файловую систему WSL.

```sh
bash xnu/apply.sh
./xnu-build.sh -j6
bash xnuloader/build.sh renoir
```

Для пересборки userland файлы iOS можно снова скачать из Apple IPSW командой `bash ios165/fetch.sh`. Для обычного запуска это не требуется: готовые packfs сохранены в релизе. Перед GL-сборкой заново собери Mesa (`bash tools/mk-mesa.sh`), затем:

```sh
GL=1 REST=1 WIFID=1 SHARE=1 RC_JOBS=rc.jobs.renoir bash userland/build.sh
QEMU_RAM_GB=6 CMDLINE=-v bash qemu/run-ios.sh 600
```

Последние изменения проверены сборками и рабочим столом/Settings в QEMU, но ещё не повторной загрузкой телефона. QEMU не проверяет физические драйверы Renoir.

Перед удалением локальной папки проверь обе ветки, семь assets и SHA256SUMS в релизе. Сохрани доступ к GitHub: токен в архивы не входит. Исходный IPSW, распакованная iOS, старые RAW/логи и сборочные кэши не архивируются. Личные данные Android этот комплект не резервирует.
