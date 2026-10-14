# Darwin / iOS 16.5 на Mi 11 Lite 5G (renoir)

Статус: начальный порт загрузчика, драйвер FocalTech FT3658U, экспериментальный
профиль Adreno 642 и защита аппаратных
драйверов. На телефоне подтверждены XNU/PID1, четыре CPU, EPSS, касания FT3658U
и тестовый кадр Adreno 642. iOS загрузил SpringBoard и Settings с GLES/Mesa FD642;
на снимке экрана Settings отображается без наложения консоли.
В аппаратных тестах Wi-Fi прошли WPA2, DNS, HTTP и HTTPS; проверенный профиль
и ограничения повторного запуска приведены в разделе Wi-Fi в конце документа.
Стабильность и все аппаратные функции ещё проверяются. Это не готовый образ
для телефона. Готовые файлы `prebuilt/` относятся к redwood.

## Основа

- Darwin: `vcvkk/darwin-redwood`, начальная точка `3be3cc7`.
- UEFI: Project Silicium / Mu-Silicium, фиксированный коммит из `uefi/BASE`
  (`e51cd877e31c8fbb322032dc4cb6715e83d25ad3`). В нём уже есть `renoirPkg`,
  двоичные драйверы подключаются штатным подмодулем `Binaries`.
- Физические параметры сверены с `Resources/DTBs/renoir.dts`,
  `Platforms/Xiaomi/renoirPkg` и `Silicon/Qualcomm/CedrosPkg` этого коммита.

В renoir установлен SM7350 / Snapdragon 780G, Adreno 642. Это отличается от
SM7325 / Snapdragon 778G и Adreno 642L в redwood. Общая архитектура ARM64
сама по себе не подтверждает совместимость периферийных драйверов.

| Блок | Параметры renoir / состояние |
|---|---|
| GICv3 | Distributor `0x17a00000`, redistributors `0x17a60000` |
| PSCI | SMC; MPIDR CPU0–CPU7: `0x000`–`0x700` |
| EPSS | `0x18591000`, `0x18592000`, `0x18593000`; проверены CPU4–6 на 2208 МГц и CPU7 на 2400 МГц |
| Framebuffer | GOP; штатная конфигурация 1080×2400, область дисплея `0xe1000000` |
| UEFI FD | `0x9fd00000`, 2 МиБ |
| XNUP | `0xf0000000`, 64 МиБ; добавлена резервация в карте памяти renoir |
| Сенсор | FT3658U `0x5652`; XNU читает реальные касания через GPIO SPI. SPI `0x988000`, GPIO20–23, reset GPIO30, IRQ GPIO31 |
| GPU | A642: GMU, TrustZone, SMMU, командный процессор, тестовый кадр и Settings через Mesa FD642 проверены на телефоне. По умолчанию программный рендер |
| Кнопки | PMK8350 SID0 PON и PM8350 SID1 GPIO6; реальные нажатия/отпускания power и обеих кнопок громкости зарегистрированы в iOS |
| Watchdog | Вызовы Haven SMC redwood не включены для renoir; автоматический возврат по watchdog не обещается |

Обе платы имеют framebuffer по одному адресу. Поэтому отдельный
`loader-renoir.efi` выбирает renoir явно, а `/chosen/darwin-board` передаёт
физическую плату ядру. Apple-идентификаторы остаются iPhone10,3 для совместимости
с исходным userland. Без распознанного физического идентификатора драйверы с
адресами платы не обращаются к MMIO. После изменений ядро и загрузчик нужно
пересобирать вместе, в том числе для redwood.

Логи renoir хранятся в RAM и выгружаются по USB. Запись `logdump` отключена
как в EFI-загрузчике, так и в диагностическом коде UEFI.

На экземпляре пользователя Android зарегистрировал `fts_ts` на
`/devices/platform/soc/988000.spi/spi_master/spi0/spi0.0/input/input2`;
журнал содержит события `[FTS_TS]fts_input_report_b`. Это подтверждает
вариант FocalTech. Чтение пользователем `spi0.0/fts_driver_info` подтвердило
IC ID `0x5652`, совпадающий с `FTS_CHIP_TYPE_MAPPING` драйвера
`focaltech_3658u` в OKX, где задан `FTS_CHIP_TYPE _FT3658U`.
Драйвер: Focaltech V3.2 20200422; координаты (0,0)–(1080,2400),
10 касаний, SPI mode 0, max_freq 12000000. Android сообщил reset GPIO337,
interrupt GPIO338, Linux IRQ283; DTS задаёт локальные TLMM GPIO30/31.
Linux IRQ283 не является номером GIC SPI для прямого переноса в XNU.
В DTS SPI задано 6 МГц, тогда как активный Android-драйвер сообщает 12 МГц;
при переносе нужно учесть настройку частоты самим драйвером.
Перенос сенсора этого экземпляра должен опираться на данный драйвер,
а не на Goodix GT9916/GT9897T.

## Сравнение с redwood по характеристикам и Android-драйверам

[Характеристики Mi 11 Lite 5G](https://www.mi.com/uk/product/mi-11-lite-5g/specs/)
и [POCO X5 Pro](https://www.mi.com/pk/product/poco-x5-pro-5g/specs/) подтверждают
LPDDR4X, UFS 2.2, восьмиядерные процессоры до 2,4 ГГц и AMOLED 1080×2400 у обеих
моделей. Частоты экранов различаются: 90 Гц у renoir и 120 Гц у redwood.

`sm8350` — общее Android-дерево для семейства платформ. В локальном
`/home/wannq/renoir_tests/sm8350-kernel-OKX` (коммит
`08bbb0c150ead6175a8ce862c7cf4147bf8931bb`) действительно присутствуют DTS
renoir и redwood. Выводы ниже также сверены с исходниками LineageOS
`android_kernel_xiaomi_sm8350`, ветка `lineage-23.2`:

- [renoir-sm7350.dtsi](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/renoir-sm7350.dtsi):
  контроллер SPI `xiaomi,k9-spi`, reset GPIO30, IRQ GPIO31, питание от L7C/L2C,
  прошивка Goodix `goodix_gt9897t_fw_k9.bin`.
- [renoir_QGKI.config](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/configs/vendor/renoir_QGKI.config):
  Goodix BRL и FocalTech 3658U — оба поддерживаются Android-ядром.
- [redwood-sm7325.dtsi](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/redwood-sm7325.dtsi):
  другая распиновка сенсора: reset GPIO105, IRQ GPIO81, AVDD GPIO107; GT9916
  нельзя переносить только заменой разрешения дисплея. В SPI-протоколе
  GT9897T четыре dummy-байта после адреса чтения, у текущего GT9916-драйвера три.
- [xiaomi-sm7350-common.dtsi](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/xiaomi-sm7350-common.dtsi)
  и [xiaomi-sm7325-common.dtsi](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/xiaomi-sm7325-common.dtsi):
  общий PMK8350 для power/resin, GPIO6 для Volume Up. На renoir это PM8350,
  на redwood PM7325; адрес периферии SID1:`0x8d00` совпадает, как и арбитр EE0.
  Поэтому общий драйвер кнопок переиспользован с именем PMIC для каждой платы.
- [adreno-gpulist.h](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/drivers/gpu/msm/adreno-gpulist.h):
  A642/A642L используют общие A6xx GMU-операции, `a660_sqe.fw`, `a660_gmu.bin`,
  `a660_zap`, таблицы HWCG и защиты. GMEM различается: 1536 КиБ / 512 КиБ;
  FIFO threshold: `0x00300000` / `0x00200000`. В штатном DT renoir chipid
  `0x06060010`, тогда как XNU-драйвер redwood использует `0x06030500`.
  Это основание переиспользовать общую реализацию с профилем A642, но перед
  включением также нужно сверить GMU chip encoding, RPMh, OPP, SMMU и firmware.

Результат сборки 13 октября 2026: оба EFI-загрузчика, Mach-O ядро и UEFI
renoir собраны. `xnu-build.sh` теперь по умолчанию вызывает штатную цель XNU
`build`, которая компилирует/линкует ядро и завершилась с кодом 0.
Явная цель `./xnu-build.sh all` по-прежнему включает Apple kext SDK symbolsets,
для которых в этом standalone-порту отсутствует часть экспортов.
Эта проверка не отключена. Журнал сборки ядра: `logs/xnu-kernel-build.log`.
В QEMU 11.1.2 проверены минимальный PID1, четыре CPU через PSCI и возврат
по таймеру. Полный iOS userland с исправленной RAMFS на четырёх CPU дошёл
до экрана блокировки и домашнего экрана; свайп работает через virtio.
Журнал: `logs/qemu-ramfs-fixed-7gb.log`, снимок: `logs/qemu-ramfs-home.png`.
На телефоне отдельно проверены минимальный PID1, SMP и EPSS,
касания FT3658U и выполнение команд GPU. Wi-Fi renoir ещё требует переноса.

При проверке исправлены два общих дефекта: загрузчик ждёт завершения DMA
настройки ramfb вместо немедленного чтения результата; RAMFS использует
ожидающее выделение больших таблиц страниц для записи/расширения файла
(XNU отказывает большим выделениям с Z_NOWAIT). Путь pageout остаётся
неблокирующим. Отдельные отказы выделения страниц в pageout ещё встречаются
в журнале и требуют дальнейшей проверки; полноценная стабильность не заявляется.

Во время работы подтянуты коммиты апстрима до `b1616f7` (virtio-сеть, кнопки и Wi-Fi/ath11k),
локальные изменения renoir сохранены. Пользовательский монитор проверяет
origin каждые 30 минут. SDK и cctools скачаны в игнорируемый `build-tools/theos`;
`xnu-env.sh` использует их, если отсутствует `$HOME/theos` и не задан `$THEOS`.

Обновление `b1616f7`: приняты WPA2, Ethernet data path и фоновый запуск `wifi=1`.
В апстриме отсутствуют упомянутые в последних коммитах `redwood_sta.h`,
`redwood_apple80211.c` и реализация station boundary на стороне ядра.
Поэтому `wifi/lx/src/lx_80211.c` и `lx_bus.c` временно сохранены на последней
полной версии `afd8925` (WPA2 и обычный сеанс уже есть); `WIFID=1` явно
отклоняется сборщиком, пока недостающие исходники не появятся. Определения
неизвестного ABI не выдумывались. На renoir аппаратный путь WPSS отключён
проверкой платы до QMI, MMIO и создания рабочего потока. Наличие
апстримного `com.redwood.wifi` в userland не означает поддержку радио renoir.
Проверки обновления: ath11k, XNU и userland собраны с кодом 0; WPA2 —
195 проверок без ошибок, проверки платы/FT3658U/Adreno пройдены. Регрессионный
QEMU-прогон на четырёх CPU с `wifi=1` запустил SpringBoard, показал framebuffer,
отклонил аппаратный путь Wi-Fi и штатно вернул управление загрузчику через
180 секунд (`logs/qemu-renoir-b1616f7.log`); panic/SIGSEGV/usertrap не найдено.
Полная работа нового Wi-Fi на renoir этим прогоном не подтверждается.

### Wi-Fi renoir: аппаратная проверка PCIe

Android на подключённом экземпляре определил PCIe endpoint `17cb:1103`
(`cnss_pci`, WCN6855 / QCA6490), а не WCN6750/WPSS redwood. В Android
соединение работало на 5 GT/s, x1; BAR0 был назначен на `0x60400000`, размер
2 МиБ. Это адрес Android, его нельзя считать готовым назначением BAR в UEFI.
Firmware `amss20.bin`, `m3.bin` и данные платы `bd_k9gl.elf` скопированы с
устройства в игнорируемый `fw-wifi/renoir/`, их SHA256 сверены с оригиналами.
Android действительно загружает `bd_k9gl.elf` (59916 байт), а не общий
`bdwlan.elf` (59912). SHA256 BDF:
`3d6f55af3d733e4d4e68f765ebf575d28e32dcbe0b3921ffc18b1d5240525be9`.
Общий `regdb.bin` больше не отправляется: Android ищет отсутствующий
`regdb_xiaomi.bin` и работает без него.
Сборщик userland кладёт их отдельно в `/fw-wifi-renoir/`.

В `redwood_wifi.c` добавлен экспериментальный путь `wifi_step=1 wifi_probe=N`
для renoir. Обычный `wifi=1` пока сообщает об отсутствующем PCIe/MHI-транспорте
и не публикует сетевой интерфейс. Пробы 1–7 проверяют GCC/TLMM, GDSC,
такты, PARF, L6B/L10C и PHY по последовательности из OKX `shima-pcie.dtsi`.
Они выполнены на телефоне через резидентный RAM-загрузчик, без записи разделов.
После включения PHY статус `0x86` снял бит not-ready, PIPE clock заработал;
проба 7 прочитала корневой PCIe ID `17cb:010f`. Регистры хоста восстановлены,
временные запросы L6B/L10C сняты. Лог: `logs/phone-renoir-wifi-dbi-live.log`.
WLAN_EN не поднимался; endpoint и передача данных этим тестом не проверены.

Проба 8 читает PMIC через SPMI observer, без записи регистров PMIC и без
изменения голосов регуляторов. На устройстве arbiter `0x50020000`; управляющие
блоки SMPS в доступной таблице не обнаружены. Это не подтверждает ни наличие,
ни отсутствие напряжения на S2C/S10B/S11B/S12B. Лог:
`logs/phone-renoir-wifi-rails.log`.

Продолжение 14 октября: проба 9 успешно прочитала APPS-запросы VRM через RPMh
(`logs/phone-renoir-wifi-votes.log`). Чтение показывает запрос этого клиента,
а не итоговое физическое напряжение. Формат read-команды проверен по
[Qualcomm rpmh_read](https://patchew.org/linux/20260801-b4-read-rpmh-v5-v6-0-9fcb54928523@oss.qualcomm.com/20260801-b4-read-rpmh-v5-v6-1-9fcb54928523@oss.qualcomm.com/).
Проба 10 сохранила прежние запросы, подала S2C=952 мВ, S10B=1800 мВ,
S11B=1880 мВ, S12B=1350 мВ по OKX, проверила readback voltage/enable и
восстановила исходные значения (`logs/phone-renoir-wifi-radio-power.log`).

Пробы 11–13 проверены с новым статическим PID1 (`tools/mkprobe.sh`):
поднялось PCIe-соединение, через временный CFG0 iATU прочитан endpoint
`17cb:1103`, revision 1, class `028000`, исходный command=0 и BAR0=4
(неназначенный 64-битный BAR). Временный BAR0 `0x60400000` и MEM iATU
дали доступ к MHI: length `0x100`, version `0xdeadbeef`, BHI offset `0x100`,
BHIE offset `0x224`, BHI execution environment 0 (PBL). Это начальный
загрузчик чипа, не работающий WLAN firmware. Endpoint bus mastering
не включался, MHI doorbell не записывался. BAR, окна, запросы питания и
GPIO восстановлены, PID1 продолжил работу. Лог: `logs/phone-renoir-wifi-mhi.log`.

Во время проверок старый вспомогательный PID1 получил `EXC_ARM_SP_ALIGN`
(Mach exception 1, code `0x103`, SP `0x16fdffe88`). Причина — вход напрямую
в C без выравнивания стека. Новый `tools/probe_pid1.c` выравнивает SP до
16 байт перед вызовом C; повторные пробы прошли без panic. Временные
диагностические изменения `sleh.c`/`ux_exception.c` убраны из дерева XNU
перед повторными сборками. Изменений для About не добавлялось.

Проба 14 прочитала apps SMMU: SCR0 `0x230406`, IDR0 `0x4c017e59`,
IDR1 `0x6000003c`, 4 из 89 match entries заняты, ни одна не покрывает
renoir SID `0x2401`. Проба 15 использовала свободные match/context 3,
проверила настройку SID `0x2401` с пустыми таблицами, затем восстановила
SMR/S2CR/CBAR/CBA2R и конфигурацию контекста с проверкой readback.
Пустые таблицы не разрешают ни одного DMA-адреса; endpoint оставался выключен.
Лог: `logs/phone-renoir-wifi-smmu-empty.log`. Общая функция SMMU теперь
принимает SID/mask, отказывается от пересечения с существующим stream;
redwood вызывает её с прежними `0x1c00/1`.

Пробы 16–22 добавляют BHI/BHIE и MHI поверх временного отображения DMA:
непрерывный firmware-буфер, IOVA `0xa0000000`, SID `0x2401`, таблица
BDF-to-SID PARF для `01:00.0`. При завершении сначала утверждается PERST,
затем восстанавливаются таблица SID и конфигурация SMMU, освобождается буфер.
При panic endpoint также сбрасывается до снятия отображения.

Проба 16 загрузила первые 512 КиБ исходного `amss20.bin` через BHI:
status `0x80000001`, EE=1 (SBL), MHI READY (`0x101`), без SMMU faults.
Проба 17 передала весь файл (5 197 824 байта, 10 BHIE vectors) и после
исправления MSI достигла EE=2 (AMSS), MHI M0 (`0x201`). Контексты MHI
имеют ABI 44 байта, смещения rbase/rp/wp 12/28/36 по OKX и Linux.
При чтении/записи 64-битных полей через некэшируемый alias используются
два выровненных 32-битных доступа.

Причиной наблюдаемой порчи контекста оказался запуск без настроенного MSI:
уведомления оставались выключены, адрес назначения был нулевым. Первое
событие M0 попадало в кольцо, следующее событие EE повреждало его контекст.
В диагностических пробах MSI теперь получает отдельный sink в отображённой
RAM (`control + 0x9000`), без доставки IRQ процессору. На WCN6855 это
32-битная MSI capability по `0x50`, mask-capable, 32 vectors; конфигурация
проверяется чтением до первого BHI doorbell и восстанавливается после
отключения DMA. Это временный режим с опросом, не готовый обработчик IRQ.
После этой настройки повреждение исчезло и переход в AMSS повторился.
Лог: `logs/phone-renoir-wifi-bhie-msi32.log`.

Проба 18 успешно выполнила START для IPCR channels 20/21: обе command
completion имеют код 1; контексты перешли в running (state 2).
Проба 19 отправила QRTR v1 HELLO через channel 20 и получила через 21
ответ HELLO и NEW_SERVER: WLAN QMI service `0x45`, instance `0x101`,
node 7, port 1. Все указатели completion и размеры RX проверяются перед
обращением к памяти; одновременно опубликован только один RX-буфер.
Логи: `logs/phone-renoir-wifi-ipcr-start.log`,
`logs/phone-renoir-wifi-ipcr-hello.log`.

Проба 20 отправила диагностический QMI target capability request `0x24`.
TX подтверждён, получен корректный QMI ответ result=1/error=90
(`QMI_ERR_INCOMPATIBLE_STATE_V01` в OKX). Это подтверждает двусторонний
обмен QMI, но запрос до штатной инициализации WLAN отвергается.
Лог: `logs/phone-renoir-wifi-qmi-cap.log`.

Проба 21 успешно зарегистрировала QMI indications (`0x20`, result=0/error=0).
Проба 22 передала host capability (`0x34`, result=0/error=0) и получила
REQUEST_MEM (`0x35`): DDR type 1 размером `0x4e0000`, CAL type 4 размером
`0x398000`. Запрос распарсен с проверкой границ и числа конфигураций.
Память в этой пробе ещё не выделяется и адреса прошивке не передаются.
Логи: `logs/phone-renoir-wifi-qmi-register.log`,
`logs/phone-renoir-wifi-qmi-hostcap.log`.

Пробы 23–26 прошли RESPOND_MEM и FW_MEM_READY, загрузку regdb и
bdwlan.elf, M3_INFO и FW_INIT_DONE. DDR и CAL требуют выравнивания IOVA
до следующей степени двойки размера: адреса `0xa0800000` / `0xa1000000`.
Выравнивание только до 16 КиБ вызывало RDDM. M3 размещена по `0xa1400000`.
Лог полного успешного bootstrap: `logs/phone-renoir-wifi-qmi-m3-quiet.log`.

Проба 27 подключает настоящий ath11k PCI backend: динамическое окно
регистров, отдельный пул DMA 80 МиБ, постоянный MHI/QRTR worker с очередью
копий TX. QMI проходит до FW_INIT_DONE, но включение mission mode вызывает
падение firmware (EE=3, MHI SYSERR/RDDM), до HTC/WMI и сканирования.
RDDM в первом запуске успешно прочитан: `cmnos_thread.c:4713:0x8Asserted in:
0x188f0a4:0x188f27c, line#453`. Лог: `logs/phone-renoir-wifi-ath11k-rddm.log`.
В последующих прогонах RDDM иногда не завершается, причина пока неизвестна.
Сохранённые смещения BHI/BHIE используются после SYSERR вместо повторного
чтения регистра со смещением. Парсер RDDM проверяет границы таблицы и файлов.

Профиль QCA6490 сверён с OKX: WMI CE2/3 имеют буферы 3520 байт,
CE2 содержит 64 RX-дескриптора, CE7 не используется для WMI, добавлено
назначение PACKET_LOG на CE5. shima.dtsi требует cold-boot calibration;
она включена, но команда mode 7 тоже приводит к RDDM, ещё до WLAN_CFG.
Проверка внутреннего sleep clock проблему не устранила. BDF response
сообщил internal PA; RF TCS `0x42204` уже содержит enable=1, опрос был
только на чтение (`logs/phone-renoir-wifi-ath11k-pa-survey.log`).
Проба 28 воспроизвела падение mode 7 на ручном QMI bootstrap, без ath11k
и его DMA-пула (`logs/phone-renoir-wifi-qmi-cal.log`). Дополнительный
ANTENNA_SWITCH `0x47` вернул error 94 (not supported), поэтому probe 28
с запросом антенны прерывается до калибровки
(`logs/phone-renoir-wifi-qmi-ant-cal.log`).

Обычный `wifi=1` на renoir по-прежнему не включает экспериментальный DMA.
Остались устранение падения firmware, CE/HTC/WMI, сканирование, WPA2,
постоянное питание и сетевой интерфейс. Подключение к сети на renoir
не подтверждено. Все аппаратные пробы выполнялись загрузкой в RAM,
разделы телефона не записывались.

Проверки: XNU собран. `tools/test_renoir_bhi.py` исполняет настоящий код
BHI/BHIE/MHI с ASan/UBSan: ошибки firmware/выделения/отображения, отказ MSI,
таймауты и ошибки загрузки, command completions, указатели и длины IPCR,
проверка границ QMI TLV, сброс перед освобождением и восстановление регистров.
`tools/test_renoir_mhi_layout.py` проверяет ABI, кольца, BHIE vectors и
границы RDDM. `test_renoir_pci_bus.py` проверяет реальные функции окна PCI и
выравнивания DMA-пула; `test_renoir_mhi_runtime.py` — владение TX-буфером,
очередь, backpressure и ошибки выделения. Последняя сборка PCI backend
прошла минимальный QEMU: exit 0, PID1, штатный возврат
(`logs/qemu-renoir-wifi-pci-smoke.log`).
Дополнительные проверки RPMh, питания, PCIe и SMMU:
`test_renoir_rpmh.py`, `test_renoir_power.py`, `test_renoir_link.py`,
`test_renoir_config.py`, `test_renoir_mhi_survey.py`, `test_renoir_smmu.py`.
Минимальный QEMU с четырьмя CPU, `wifi=1` и статическим PID1 вернулся
в загрузчик (`logs/qemu-renoir-mhi-words.log`). Последняя сборка также
прошла минимальный прогон: exit 0, PID1 и штатный возврат
(`logs/qemu-renoir-mhi-final-smoke.log`). QEMU не эмулирует WCN6855
и не подтверждает аппаратный Wi-Fi. Полный прогон iOS через `qemu/run-ios.sh 600` с четырьмя CPU запустил
launchd/BackBoard/SpringBoard, но завершился внешним timeout (exit 124),
без штатного возврата гостя. После снятия Apple logo снимки были чёрными,
несмотря на события ввода в журнале; UI-регрессия не считается пройденной.
Аппаратное радио в QEMU не проверялось. Журнал:
`logs/qemu-renoir-mhi-ios-600.log`; снимки `logs/qemu-renoir-mhi-ios-600.png`,
`logs/qemu-renoir-mhi-ios-home.png`. Причина отсутствия изображения пока
не установлена; к новой MHI-ошибке этот результат не приписывается.
Origin переписан с `b1616f7` на `a4eefb7`; пять новых коммитов объединены
merge-коммитом `81b0612`. Локальная работа сохранена в stash
`cf154c9dba4cc680335a35b59b93996db79b55e6` и восстановлена; конфликты
redwood_input.h и redwood.patch разрешены. PM7250B battery ограничен
redwood; userland при неизвестном SOC возвращает исходное состояние батареи.
Сборка с ath11k прошла; минимальный QEMU после merge: exit 0, PID1 и
штатный возврат (`logs/qemu-renoir-a4eefb7-smoke.log`).

После исключения общего regdb cold calibration завершилась успешно,
но переход из calibration в mission без перезапуска firmware приводит к RDDM.
Прямой mission с cal_done=0 прошёл до HTC/WMI unified ready за 1519 мс,
транспорт не падал, mode OFF выполнен (`logs/phone-renoir-wifi-k9gl-mission.log`).
Поэтому cold calibration теперь только явная диагностика `wifi_cal=1`.
HOST_CAP дополнен реальным диапазоном IOVA 256 МиБ, WAKE MSI=13
(нулевая база polled sink), secondary host build и feature list без
неподдерживаемого PCIe DRV. Кодек проверен `test_renoir_hostcap.py`.
L11C (2,8 В) для антенного переключателя включается как в Android и
восстанавливается после пробы; тест частичных ошибок питания расширен.
Сканирование ещё не было выполнено: FW имеет нулевой MAC, а без MAC
station не создаётся. Для следующей пробы используется прочитанный
из Android локально администрируемый адрес, сохранённый в игнорируемом
`fw-wifi/mac`; это не утверждение о заводском NV MAC.

## Подготовка сборки

Все команды выполняются в Linux / WSL archlinux, из корня репозитория.

```sh
xnuloader/build.sh renoir
xnu/apply.sh                  # только если дерева xnu-src ещё нет
xnu-deps/setup.sh             # требует theos toolchain и iPhoneOS16.5.sdk
./xnu-build.sh -j8
uefi/apply.sh renoir          # только если Mu-Silicium ещё нет
python3 -m venv venv
venv/bin/pip install -r Mu-Silicium/pip-requirements.txt
cd Mu-Silicium
source ../venv/bin/activate
python3 build_uefi.py -d renoir -r RELEASE
```

`uefi/apply.sh renoir` использует штатный порт renoir и общий XNU-hook,
не копирует карту памяти и бинарные драйверы redwood. Его второй аргумент
`--no-submodules` предназначен только для проверки наложения патчей,
без подмодулей UEFI не собрать. `MU_DIR` позволяет подготовить дерево в другом
каталоге; упаковщик и экспорт пока используют стандартный `Mu-Silicium/`.

`mkxnuimg.py --device renoir` требует локально собранный renoir FD и маркер
`Mu-Silicium/.xnu-device`; готовый FD redwood не подставляется.
`XL_DEVICE=renoir` выбирает соответствующий загрузчик и проверяет product
устройства перед командой fastboot boot. Аппаратные проверки выполняются строго
через `fastboot boot` и передачу файлов в RAM; запись разделов запрещена пользователем.

## Проверки и порядок продолжения

1. `python3 tools/test_renoir.py`: проверки выбора платы, отказа от чужого
   UEFI и упаковки Android boot image. `xnuloader/build.sh` собирает EFI обеих плат.
2. Полная сборка XNU и UEFI. Наличие старого ядра в `prebuilt/` не считается
   успешной сборкой порта.
3. Проверка полного userland в QEMU.
   В QEMU нужен обычный `loader.efi`, собранный без выбора renoir:
   `xnuloader/build.sh redwood`. `loader-renoir.efi` содержит физические
   адреса телефона и в QEMU virt не применяется. Проверять запуск launchd,
   backboardd, SpringBoard, ввод virtio и штатный возврат в загрузчик.
   Команда пользователя: `CMDLINE="-v" qemu/run-ios.sh 600 2>&1 | tee boot.log`.
   Отдельный прогон с одним CPU по умолчанию дошёл до домашнего экрана,
   принял свайп и вернул управление загрузчику по таймеру 600 секунд;
   в журнале нет usertrap/SIGSEGV или panic. Обои не отрисовались:
   фон блокировки чёрный, домашнего экрана белый; зарегистрированы таймауты
   расширений PosterBoard. Это остаётся ограничением проверки.
4. После успешных общих проверок — краткий сеанс на телефоне, сначала
   возврат загрузчика и минимальное ядро на одном CPU, без `touchscreen`,
   `buttons`, `cpufreq`, `gpu`, `adreno` и без переноса исполнения на CPU7.
   Затем отдельно PSCI/SMP и EPSS, с журналом каждого этапа.
5. Проверить FT3658U на телефоне: ID/CRC, одно касание и отпускание, свайпы,
   одновременные касания, затем длительный ввод и восстановление после ошибок.
   Отдельно проверить кнопки. GPU переносится после стабильной программной графики.

QEMU virt не эмулирует SM7350, PMIC, сенсор и Adreno renoir. Успешный запуск
iOS в QEMU подтверждает общую часть порта, но не готовность образа телефона.

## Adreno 642

`redwood_adreno_profile.h` отделяет параметры двух плат. Для renoir:
chip ID `0x06060010`, передаваемый GMU как `0x16060000` (target в старших
битах), GMEM 1536 КиБ, primitive FIFO `0x00300000`, speed/gaming fuse
`0x1e1`/`0x1ed`. Начальный OPP ограничен 285 МГц с RPMh level 64;
верхние частоты не включены. Для A642 добавлена настройка UCHE CMDQ `0x66906`.
GCC, GPUCC, GMU, SMMU, их потоки и область zap `0x8b71a000` сверены с shima DTS.
Измерительный GCC mux различается: `0x13c` на shima/renoir, `0x146` на redwood.
Он выбирается профилем платы; после исправления на телефоне измерены
GMU 200 МГц, HUB/AHB 150 МГц и XO 19,2 МГц.

13 октября аппаратные этапы 1–9 и 13–22 прошли с firmware этого телефона.
TrustZone принял подпись, расположение и запуск zap shader; GMU запустил
очереди, 3D core выполнил запись контрольного слова. GPU нарисовал три полосы:
проверены пиксели `00 80 ff ff`, `ff ff ff ff`, `ff 80 00 ff` и показ кадра
на framebuffer. Логи: `logs/phone-renoir-gpu-step16.log`,
`logs/phone-renoir-gpu-step21.log`, `logs/phone-renoir-gpu-step22.log`.
Затем полный userland загрузил Settings с `gpu=1`: Mesa сообщает renderer
`FD642`. Снимок: `logs/phone-renoir-ios-screen.png`, журнал
`logs/phone-renoir-ios-clean-live.log`. Исправлен общий путь прямого вывода
кадров: `kPEGraphicsMode` меняет режим, но для прекращения записи экранной
консоли также требуется `kPEReleaseScreen`. Длительная стабильность и все
режимы GLES ещё не проверены.

Android на телефоне пользователя подтвердил SM7350, Adreno642v1,
chip ID `0x06060010`, DDR type 7 (LPDDR4), частоты 490/443/365/285 МГц.
Vendor a6xx_init для DDR4 у A642 меняет highest-bank-bit с DT-значения 15
на 14. Профили ядра и Mesa используют 14. Патч `tools/mesa/renoir-a642.patch`
добавляет точное совпадение FD642 перед общим FD660 с wildcard patch ID;
остальные параметры пока наследуют общий профиль A660 и требуют аппаратной
проверки. Настройка банка 16 из общего профиля несовместима с выбранной в ядре 14.

Firmware скопирована с работающего Android в игнорируемый `fw-gpu/renoir/`;
SHA-256 совпали с файлами на телефоне. Логи: `logs/android-renoir-gpu.txt`,
`logs/android-renoir-gpu-details.txt`. Не включать эти бинарники в коммиты.
`userland/pack-gpu-firmware.sh` кладёт их в отдельный `fw-renoir/` малого образа;
набор `fw/` остаётся для redwood. Автоматической подстановки firmware redwood
для renoir нет. При отказе TrustZone в подписи или памяти zap запуск renoir
прекращается; наличие старого zap не считается подтверждённым успехом.

Mesa 25.0.7 собрана с `softpipe,freedreno`; userland пересобран с `GL=1 REST=1`.
В будущем запуск с `gpu=1` требует именно такого малого образа, чтобы iOS
использовала OpenGL ES через Mesa. Без параметра остаётся программный рендер.
Проверки: `python3 tools/test_adreno_profiles.py` и
`xnu-deps/build/mesa/venv/bin/python3 tools/test_mesa_renoir.py`.
Они проверяют реальные функции выбора ID/GMEM/OPP и разделение firmware,
но не доступ к регистрам, загрузку GMU или выполнение команд GPU на телефоне.

Параметры пользователя для будущего запуска телефона:
`XL_DEVICE=renoir XL_CMDLINE="-v touchscreen=1 cpufreq=1 bootcpu=7 cpus=4" ./xl run`.
Выбор `XL_DEVICE=renoir` обязателен для выбора образа платы. `touchscreen=1`
включает FT3658U на renoir; драйвер GT9916 остаётся только для redwood.

## FT3658U / fts_ts

`xnu/files/bsd/dev/renoir_fts.c` использует GENI SE10 (wrap0 S2), режим SPI 0.
На этом телефоне GENI firmware отключает FIFO (GPI-only), поэтому используется
GPIO SPI: MISO20, MOSI21, CLK22, CS23, задержка 1 мкс. При доступном FIFO
частота ограничена 12 МГц; фактическая зависит
от доступного источника GCC и целочисленного делителя и печатается в журнал.
`fts_spi_hz=1000000` позволяет снизить целевую частоту для диагностики
(допустим диапазон 1–12 МГц). Используются L2C 1,8 В и L7C 3,3 В через RPMh.

Драйвер сбрасывает контроллер, проверяет ID приложения `0x5652` и рабочий режим.
Ответы SPI принимаются только с корректными статусом и CRC; до трёх попыток,
с паузой CS high 150 мкс. Контакты преобразуются в существующие DOWN/MOVE/UP
с диапазоном 0–65535 и `touch_flip`. Повреждённые кадры не меняют текущие
контакты; после 125 последовательных ошибок пальцы отпускаются и выполняется
ограниченное восстановление сбросом. Пустой CRC-корректный кадр `ff` при
неактивном IRQ и отсутствии контактов не считается ошибкой. Активные контакты
опрашиваются каждые 8 мс, пустой сенсор — каждые 80 мс. При неподходящем ID
драйвер прекращает работу с диагностикой. Перепрошивка сенсора не выполняется.

В аппаратном прогоне XNU получил ID `0x5652` и реальные координаты
344,1597; 376,1553; 234,1895; 839,2064. За 30 секунд не было восстановлений
сбросом (`logs/phone-renoir-touch-idle.log`). При полном запуске iOS backboardd
зарегистрировал встроенный digitizer; журнал `logs/phone-renoir-ios-clean-live.log`
содержит начало касания и последовательные движения пальца. Мультитач и
длительный ввод ещё требуют проверки.

Проверка на хосте: `python3 tools/test_renoir_fts.py` — CRC, повторы SPI,
некорректные кадры, десять контактов, движение/отпускание, отражение координат
и запрет запуска на других платах; используется ASan/UBSan. Это проверяет
протокол и события, но не доступность тактов, шин питания и SPI на телефоне.

Регрессия 13 октября: ядро с FT3658U дошло в QEMU на четырёх CPU до домашнего
экрана с цветными обоями, приняло свайп и штатно вернулось в загрузчик.
Журнал `logs/qemu-renoir-fts-regression.log`, снимок
`logs/qemu-renoir-fts-regression-home.png`. После обновления до `257432f`
и замены задержек драйвера на ожидания планировщика выполнена повторная
компиляция/линковка и минимальная загрузка четырёх CPU с возвратом по таймеру:
`logs/qemu-renoir-fts-latest-smoke.log`. В обоих случаях FT3658U отключён
проверкой физической платы QEMU; обмен с сенсором этими прогонами не проверяется.

После обновления апстрима физические кнопки включаются вместе с `touchscreen=1`;
`buttons=0` явно отключает их, `buttons=1` включает независимо от сенсора.
На renoir журнал iOS зарегистрировал нажатия/отпускания power, Volume Up и
Volume Down (`logs/phone-renoir-ios-clean-live.log`). Звук и зарядка под XNU отсутствуют и в исходном
порту redwood; запуск powerd/mediaserverd и значки батареи/громкости не являются
проверкой этих аппаратных функций. Глубокий сон и физическое выключение renoir
также не проверены.

QEMU с зависимостями и ARM64 UEFI распакован локально в `build-tools/qemu`;
`qemu/run.sh` автоматически использует его, если системного QEMU нет.
Так сохранён существующий `/usr/bin/dtc`, конфликтовавший с пакетом Arch.


## Аппаратная проверка Wi-Fi 14 октября 2026

Полный запуск iOS на renoir с PCIe WCN6855/QCA6490 и нативной границей
Apple80211 успешно подключился к заданной сети 5 ГГц (канал 52). Точка
приняла авторизацию и ассоциацию, WPA2 завершил четырёхсторонний обмен;
установлены CCMP pairwise и TKIP group key. Для TKIP добавлена обработка
32-байтового GTK с перестановкой Michael MIC для роли станции.

В `logs/phone-renoir-ios-wifi-now3.log` зафиксированы адрес
`192.168.1.186/24`, успешное разрешение `example.com`, TCP/HTTP `200 OK`
и HTTPS `200`, 577 байт за 0,65 секунды. Это проверка на физическом телефоне,
не виртуальная сеть QEMU. Долгая работа, повторное подключение и переключение
сетей через Settings пока не подтверждены. MAC для этого теста взят из Android
и является локально администрируемым; это не подтверждённый заводской адрес.

Для Renoir используются BDF `bd_k9gl.elf`, mission mode без принудительного
cold calibration и без несовместимого generic regdb. Постоянная сессия
оставляет PCIe/MHI активными после присоединения; команды станции проходят
через сериализованный kernel STA worker. APPS RPMh TCS защищён общим mutex
для Wi-Fi и тачскрина. PM7250B battery driver апстрима ограничен redwood.

Повторная сборка ath11k/XNU и минимальный QEMU SMP4 прошли. Полный QEMU
с виртуальной сетью также выполнил DNS/HTTP/HTTPS, но весь прогон завершился
внешним таймаутом; штатный возврат этого полного прогона не подтверждён.
QEMU не моделирует физический WCN6855.

После команды хоста `oem stop` firmware переходит в RDDM при остановке
ath11k (mode 4); ошибка MHI находится после отметки `the host asked for the
end of the run`, а сетевые проверки прошли до неё. Повторная загрузка из того
же resident loader пока зависает до входа в XNU; требуется холодный перезапуск.
Это отдельное ограничение завершения/повторного запуска, не доказательство
долговременной устойчивости Wi-Fi.

В следующем обычном запуске (`loader_return_after=0`, без `wifi_loud`)
подключение не удалось подтвердить: пользовательский интерфейс загрузился,
но журнал не содержит результата старта/соединения. Сравнение файлов малых
образов показало единственное отличие — LaunchDaemon консольной сетевой
проверки. Для повторной проверки используется тот же диагностический образ
и `wifi_loud=1 wifi_quiet=1`, но без таймера. До успешного повтора нельзя
считать обычный тихий запуск проверенным.

Повторный холодный запуск с `loader_return_after=0 wifi_loud=1 wifi_quiet=1`
успешен: `logs/phone-renoir-ios-wifi-console-result.log` содержит повторные
WPA2 join, IPv4 `192.168.1.186`, DNS за 0,14 с, HTTP `200 OK` за 0,37 с
и HTTPS `200`, 577 байт за 1,04 с. Телефон оставлен в этой iOS без таймера;
консольный LaunchDaemon закончил проверку. Safari не использовался:
пользователь сообщил, что приложение сломано. Тихий профиль остаётся
неподтверждённым; успешный профиль сохраняет `wifi_loud=1 wifi_quiet=1`.


## Обновление апстрима до 85cbb19 (14 октября 2026)

В ветку renoir объединены изменения main после a4eefb7 до 85cbb19:
Apple80211/Settings и сервис configd для en0, standing-network reconnect,
block ack и ширина канала, keychain и тесты MobileWiFi, опциональная панель
HackiOS. Панель остаётся за `HACKIOS_PANE=1` и в этом прогоне не включалась.
Последний 9281288 с заменой батареи на UEFI charger stack отложен:
совместимость этого пути с renoir ещё не проверена. Prebuilt kernel Redwood
не заменяет ядро Renoir; для всех проверок использована собственная сборка.

Адаптация Renoir:

- `wifi_irq` принудительно выключен, даже при явном `wifi_irq=1`:
  новые AHB MSI vectors относятся к WCN6750, а PCIe WCN6855 продолжает
  использовать проверенный polling. MSI mapping дополнительно ограничен redwood.
- Сохранены QCA6490 CE profile, BDF bd_k9gl, TKIP GTK и DMA alignment.
  Вызовы radio_enter обновлены для аргумента атрибутов SMMU.
- `wifi_ba=1` и `wifi_wide=1` включаются по умолчанию вместе с wifi=1;
  явные значения 0 отключают их. wifi_quiet сохраняет явное переопределение.
- Сборка находит ldid в bundled Theos toolchain и подписывает тестовые
  программы с entitlements. Без этого keychain возвращал -34018.
- После отказа автоматический возврат к standing network ждёт одну секунду,
  чтобы результат ошибки успел дойти до iOS. Пауза проходит без station lock;
  новые power/leave/join requests отменяют fallback. Результат успешного
  восстановления снова публикуется обычным путём.

QEMU: полный iOS userland прошёл DNS, HTTP/HTTPS и добавление/чтение/удаление
keychain item; MobileWiFi сохранил и извлёк тестовый пароль. Журнал
`logs/qemu-upstream-85cbb19-ios.log`; после результатов QEMU остановлен хостом,
не по возврату гостя. Kernel с паузой перед fallback прошёл дополнительную загрузку SMP4:
`logs/qemu-upstream-backoff-smoke.log`.

Первый аппаратный прогон: configd сам создал Wi-Fi service, подключение
установлено на 80 МГц около 5290 МГц, WPA2/TKIP и HTTPS прошли.
Приняты пять block-ack классов, ноль отказов. MobileWiFi и keychain тесты
успешны и на телефоне. Отказ неверного пароля восстановил прежнюю сеть,
после чего HTTPS повторно вернул 200; этот прогон выявил описанную выше гонку
ASSOCIATE_RESULT. Измерений пропускной способности пока нет.


Постоянное удержание ASSOCIATE_RESULT=21 не используется: после восстановления
успех должен снова публиковаться для iOS. Применяется описанная выше пауза
перед fallback. Пользователь сообщил Unable to join после переключения Wi-Fi
в Settings на промежуточном ядре. Финальный сценарий, включая UI, требует
проверки на сборке с паузой; автоматические и ручные проверки следует проводить
последовательно, чтобы они не меняли состояние сети одновременно.

Проверки `tools/test_renoir_wifi_options.py` покрывают запрет AHB IRQ на Renoir
и явные переопределения режимов. PCI windows/DMA alignment, BHI/MHI,
RPMh/power rollback, FT3658U, GPU profiles и 195 WPA checks прошли.

`tools/test_renoir_sta_fallback.py` исполняет реальную ветку worker: ошибка,
пауза без mutex, восстановление, отмена новым power/join и очистка fallback.


Финальная аппаратная проверка варианта с паузой прошла:
`logs/phone-upstream-backoff-result.log`. Подключение 80 МГц, DHCP
192.168.1.186, DNS, HTTP 200 OK и HTTPS 200 за 0,11 с. Затем неправильный
пароль вернул result 21 через 4,2 с; прежняя сеть восстановилась, IPv4 сохранился,
DNS повторно прошёл, HTTPS вернул 200 за 0,12 с. Диагностическое задание
com.redwood.netverify штатно завершилось exit(0) и больше не меняет соединение.
Keychain и MobileWiFi тесты также прошли на этом ядре. Телефон оставлен в iOS
с loader_return_after=0. Переключение и ручной join из Settings проверяются
отдельно после завершения автоматических заданий.
