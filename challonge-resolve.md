# Challonge: что нужно разрешить

Сгенерировано 19.10.2026. Полный построчный отчёт: `venv/bin/python -m app.cli check-challonge` (из `api/`).

## 1. Турниры

| Турнир | Что не так | Что нужно решить |
|---|---|---|
| Бойцовкий Клуб 1 (`challonge.com/genshin`) | Сетка на Challonge так и не заполнена: 58 участников, 0 результатов | Не импортирован. Есть ли результаты где-то ещё? Заодно опечатка в названии («Бойцовкий») |
| HotH: Abyss Weekend 7 | На Challonge это командный турнир (17 команд), а на сайте — личные матчи 11 игроков, и он идёт в личную статистику | Считать командным (убрать из личной статистики) или оставить? |
| Abyss Fight Club — Fast Cup 2 | Командный (пары: «PmirDivizor», «KutsukiAlou»…) | Импортирован как командный: страница и сетка есть, в личную статистику не идёт. Верно? |
| Abyss Fight Club — Fast Cup 1 (`afc_fast_111`) | Брошенный дубль Fast Cup 1: 0 результатов | Пропущен |
| Abyss Fight Club 4: Group stage 1 (`afc_4_group_1`) | Дубль группового этапа с Discord-никами, не сыгран | Пропущен |
| Abyss Fight Club 4: Group stage 1jfjxjxj (`Ususjjx`), tesdtrfareg (`kjjha2v6`) | Тестовые сетки | Пропущены |
| Abyss Fight Club 4: Group stage 1 / Group Stage 2 | На Challonge финальный этап этих сеток не начат (группы сыграны) | Импортированы только групповые матчи; это нормально, плей-офф — отдельная сетка «Main Stage» |
| Все 13 Abyss Fight Club-турниров | На embed-странице Challonge нет дат | Даты оценены по номеру турнира на Challonge (на сайте помечены «≈»). Точные даты можно задать: `add-challonge-tournament <url> <title> --organizer "Astro Liber" --date YYYY-MM-DD` |

Оценённые даты:

| Турнир | Дата ≈ |
|---|---|
| Abyss Fight Club 2 — Swiss | 2024-08-16 |
| Abyss Fight Club 2 Group Stage 4-3 | 2024-10-04 |
| Abyss Fight Club 2 — Main stage | 2024-10-17 |
| Abyss Fight Club 3 — Swiss | 2025-02-13 |
| Abyss Fight Club 3 — Main Stage | 2025-03-15 |
| Abyss Fight Club — Fast Cup 1 | 2025-04-19 |
| Abyss Fight Club — Fast Cup 2 | 2025-05-03 |
| Abyss Fight Club: Weekend 3 | 2025-05-25 |
| Abyss Fight Club: Weekend 4 | 2025-06-08 |
| Abyss Fight Club: Abyss Weekend 5 | 2025-07-01 |
| Abyss Fight Club 4: Group stage 1 | 2025-07-20 |
| Abyss Fight Club 4: Group Stage 2 | 2025-08-05 |
| Abyss Fight Club 4: Main Stage | 2025-08-23 |

## 2. Похожие люди — нужно подтвердить

Совпадение вероятное, но не точное. Подтвердить: `venv/bin/python -m app.cli set-challonge-name "<имя на Challonge>" <ник или id на сайте>`.

| Имя на Challonge | Где | Похож на (игрок сайта [ник]) |
|---|---|---|
| `Astro` | Abyss Fight Club 3 — Main Stage, Abyss Fight Club 4: Group stage 1, Abyss Fight Club 2 Group Stage 4-3, Abyss Fight Club 2 — Swiss, HotH: Abyss Weekend 11 | astro_liber [Definitely not Astro]; CATASTROPHIA [CATASTROPHIA] |
| `blackheadovka` | Abyss Fight Club — Fast Cup 1, Abyss Fight Club: Weekend 3, Abyss Fight Club: Weekend 4 | Headovka [Headovka] |
| `Blaze` | Abyss Fight Club 2 — Swiss | .blaze.orig [.blaze.orig] |
| `Condee` | Abyss Fight Club 3 — Swiss | Conde [Conde] |
| `Corgi` | Abyss Fight Club 4: Group stage 1, Abyss Fight Club — Fast Cup 1 | cori [cori] |
| `coritnia` | Abyss New Gen 1 | cori [cori] |
| `Croco na dildo` | Abyss New Gen 4, Abyss New Gen Groups | crocodilo [crocodilo] |
| `Deleted Zaharita_Plays` | Abyss Fight Club 2 — Swiss | zaharita [zaharita] |
| `Desanvi` | Abyss Fight Club 2 — Swiss | maktraher [desgai] |
| `Diagolt` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 3 — Main Stage, Abyss Fight Club 2 — Swiss | mlx [diaglot] |
| `diagolt` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1 | mlx [diaglot] |
| `FaTe` | Abyss Fight Club — Fast Cup 1 | fateeb [fateeb] |
| `Floneriel` | Women Cup | floriell [floriell] |
| `Goba弥登呂` | Abyss Fight Club — Fast Cup 1 | goba [goba] |
| `hika52rr` | Abyss New Gen 2, HotH: Abyss Weekend 12, HotH: Abyss Weekend 9 | HIKARU [hika67rr] |
| `IcePhoenix` | Abyss Fight Club 2 — Swiss | CATASTROPHIA [icephoenixxx] |
| `indepreshn` | Abyss Fast Beer 2, New Gen 5 Groups | indepreshn [indepreshn]; funtik [Indepreshn] |
| `Katsuki` | Abyss Fight Club 4: Group stage 1 | Kutsuki [Kutsuki] |
| `Lanka` | Women Cup | hanka [hanka] |
| `LinLi` | Abyss Fight Club 3 — Swiss | lin_lin_ [lin_lin_] |
| `Miri` | Abyss Fight Club 3 — Swiss | Pmir [pmir] |
| `otchaRnie` | Women Cup | sploshnoe_otcharnie [sploshnoe_otcharnie] |
| `Pandora` | Women Cup | phanora [phanora]; pandorum [pandorum]; .pando4ka [.pando4ka] |
| `phapepe` | Abyss New Gen 2 | phanora [pepe] |
| `shrimpic` | Abyss Fight Club: Weekend 3 | Shrimp [Shrimp] |
| `Soul` | Abyss Fight Club 4: Group stage 1, Abyss Fast Soup 14, Abyss Fast Soup 15, Abyss Fast Soup 16, Abyss New Gen 1 | soulx_9442 [soulx_9442]; soullesswriter [soullesswriter] |
| `soul` | Abyss Fast Soup 13 | soulx_9442 [soulx_9442]; soullesswriter [soullesswriter] |
| `sunset12_` | Abyss Fight Club 4: Group stage 1 | sunset [sunset] |
| `TriconArmu` | Abyss New Gen 1 | Tricon [Tricon] |
| `ymu` | Abyss Fast Soup 13 | yu [yu] |
| `Zaharita_Plays_` | Abyss Fight Club 2 — Swiss | zaharita [zaharita] |
| `😈Павлік ᴹᴿメSigma💀` | Abyss New Gen 1 | HIKARU [😈ᴹᴿメSigma💀] |

## 3. Людей нет на сайте и похожих нет (199)

### 3a. Только в турнирах Abyss Fight Club (172)

Скорее всего, не играли на darte.gg. На странице турнира показаны без ссылки. Если кто-то играет на сайте под другим ником — привязать через `set-challonge-name`.

| Имя на Challonge | Турниры |
|---|---|
| `>|<u3HuK` | Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1 |
| `@s1affy` | Abyss Fight Club: Abyss Weekend 5 |
| `Ackerman` | Abyss Fight Club 4: Group stage 1, Abyss Fight Club: Abyss Weekend 5, Abyss Fight Club: Weekend 4 |
| `Adamius` | Abyss Fight Club 2 — Swiss |
| `Adepti_Childe` | Abyss Fight Club 2 — Swiss |
| `Adiers` | Abyss Fight Club 3 — Swiss, Abyss Fight Club — Fast Cup 1 |
| `AE_ARMAGEDDON` | Abyss Fight Club 2 — Swiss |
| `Akaashiro` | Abyss Fight Club 2 — Swiss |
| `akamexd` | Abyss Fight Club: Abyss Weekend 5 |
| `Akane` | Abyss Fight Club 2 — Swiss |
| `Akashiro` | Abyss Fight Club 2 — Main stage |
| `Alex_Shiba` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group stage 1, Abyss Fight Club 2 — Swiss |
| `AlexNumbers` | Abyss Fight Club 2 — Swiss |
| `Anny4i` | Abyss Fight Club 2 — Swiss |
| `Anzile` | Abyss Fight Club 2 — Swiss |
| `ArkashaUwU` | Abyss Fight Club 2 — Swiss |
| `Ashasv` | Abyss Fight Club 2 — Swiss |
| `AstiGum` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group stage 1 |
| `Banka Svetlogo` | Abyss Fight Club 3 — Swiss |
| `BankaSvetlogo` | Abyss Fight Club 2 — Swiss |
| `Beezy` | Abyss Fight Club 2 — Swiss |
| `Blaze169` | Abyss Fight Club 2 — Main stage |
| `Bleblizun` | Abyss Fight Club 2 — Swiss |
| `BlindSquidHeh` | Abyss Fight Club 2 — Swiss |
| `bonten` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group stage 1 |
| `Boobable` | Abyss Fight Club — Fast Cup 1 |
| `CalciferAriel` | Abyss Fight Club 3 — Swiss |
| `Castiel'` | Abyss Fight Club — Fast Cup 1, Abyss Fight Club 2 — Swiss |
| `chmlrenok` | Abyss Fight Club 2 — Main stage, Abyss Fight Club — Fast Cup 1, Abyss Fight Club 2 — Swiss |
| `ClovesCleyton` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1, Abyss Fight Club 4: Main Stage, Abyss Fight Club — Fast Cup 1 |
| `ClownArs` | Abyss Fight Club 2 — Swiss |
| `Dado` | Abyss Fight Club 3 — Swiss |
| `dado` | Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1, Abyss Fight Club — Fast Cup 1 |
| `Day` | Abyss Fight Club 3 — Swiss |
| `Deimos_` | Abyss Fight Club 3 — Swiss |
| `Deleted dessemond` | Abyss Fight Club 2 — Swiss |
| `Dillion` | Abyss Fight Club 3 — Swiss |
| `ElliMiku` | Abyss Fight Club 4: Group stage 1 |
| `elsapitocroa` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group stage 1, Abyss Fight Club — Fast Cup 1 |
| `Endermite` | Abyss Fight Club 2 — Swiss |
| `EvilNest` | Abyss Fight Club — Fast Cup 1 |
| `fallen7745` | Abyss Fight Club: Abyss Weekend 5 |
| `Fre1man` | Abyss Fight Club 2 — Swiss |
| `Frizingy` | Abyss Fight Club 2 — Swiss |
| `Fryett` | Abyss Fight Club 4: Group stage 1, Abyss Fight Club: Weekend 3 |
| `Galaksius` | Abyss Fight Club 2 — Swiss |
| `gDado` | Abyss Fight Club 4: Main Stage |
| `Godjo` | Abyss Fight Club 2 — Swiss |
| `gr4G` | Abyss Fight Club 3 — Swiss |
| `Grenka` | Abyss Fight Club 2 — Swiss |
| `Gurupatikus` | Abyss Fight Club 2 — Swiss |
| `Hanwig` | Abyss Fight Club 2 — Swiss |
| `HardStyle` | Abyss Fight Club 2 — Swiss |
| `Hey_Xen` | Abyss Fight Club 2 — Swiss |
| `i_Arioh` | Abyss Fight Club 2 — Swiss |
| `I_Arioh` | Abyss Fight Club 2 Group Stage 4-3 |
| `Igrovoy_Statut` | Abyss Fight Club 2 — Swiss |
| `Invinsik` | Abyss Fight Club 2 — Swiss |
| `Jacot_Cot` | Abyss Fight Club 2 — Swiss |
| `Jamal` | Abyss Fight Club 3 — Swiss |
| `JamMohia` | Abyss Fight Club 2 — Swiss |
| `JOHNN` | Abyss Fight Club 3 — Swiss |
| `just1ce5` | Abyss Fight Club 3 — Swiss |
| `Juuzoupz` | Abyss Fight Club — Fast Cup 1 |
| `Kano_Vater` | Abyss Fight Club 2 — Swiss |
| `KR7` | Abyss Fight Club 3 — Swiss |
| `Krizz` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 2 — Swiss |
| `kujo1_` | Abyss Fight Club: Abyss Weekend 5 |
| `kvrsye` | Abyss Fight Club — Fast Cup 1 |
| `le0n_s._kennedy` | Abyss Fight Club: Abyss Weekend 5 |
| `Lelouch` | Abyss Fight Club 3 — Swiss |
| `Lerian` | Abyss Fight Club 2 — Swiss |
| `lkxemmeji` | Abyss Fight Club 2 — Main stage |
| `lkxemmeji_19525` | Abyss Fight Club: Abyss Weekend 5, Abyss Fight Club: Weekend 4 |
| `lmeow` | Abyss Fight Club 4: Group stage 1 |
| `Lunaliel` | Abyss Fight Club 2 — Swiss |
| `Magickat` | Abyss Fight Club 2 — Swiss |
| `Makatay` | Abyss Fight Club 2 — Swiss |
| `makatay` | Abyss Fight Club 3 — Swiss |
| `Marry` | Abyss Fight Club 2 — Swiss |
| `mast_mex` | Abyss Fight Club: Abyss Weekend 5 |
| `Matras` | Abyss Fight Club 3 — Swiss |
| `maxpower` | Abyss Fight Club 4: Group stage 1 |
| `maxpower254` | Abyss Fight Club: Weekend 4 |
| `Meji` | Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1 |
| `Merm1llion` | Abyss Fight Club 2 — Swiss |
| `mexanik34` | Abyss Fight Club: Abyss Weekend 5 |
| `Mexanik35` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group stage 1, Abyss Fight Club 2 — Swiss |
| `miseri` | Abyss Fight Club 3 — Swiss |
| `Mistikal` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 3 — Main Stage, Abyss Fight Club 3 — Swiss, Abyss Fight Club 2 — Swiss |
| `Miyatochka` | Abyss Fight Club 2 — Swiss |
| `Mochi6` | Abyss Fight Club 3 — Swiss |
| `Mox111` | Abyss Fight Club 2 — Swiss |
| `Mr.Goodkat` | Abyss Fight Club: Abyss Weekend 5 |
| `mrfloor` | Abyss Fight Club: Weekend 3 |
| `MrShyriCk` | Abyss Fight Club 2 — Swiss |
| `Neo` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1 |
| `Nero` | Abyss Fight Club 2 — Swiss |
| `Neyovinex` | Abyss Fight Club 2 — Swiss |
| `nightmare` | Abyss Fight Club: Weekend 3 |
| `nightmare_1295` | Abyss Fight Club: Abyss Weekend 5 |
| `NineTeen7` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 2 — Swiss |
| `NipodZi` | Abyss Fight Club 3 — Swiss, Abyss Fight Club 4: Group Stage 2, Abyss Fight Club 4: Group stage 1, Abyss Fight Club 2 — Swiss |
| `Nipodzi` | Abyss Fight Club 3 — Main Stage, Abyss Fight Club 4: Main Stage |
| `nvnsk` | Abyss Fight Club 4: Group stage 1, Abyss Fight Club: Weekend 3, Abyss Fight Club: Weekend 4 |
| `ourson` | Abyss Fight Club 4: Group stage 1 |
| `Oyasumi` | Abyss Fight Club 2 — Swiss |
| `P-Jey` | Abyss Fight Club — Fast Cup 1 |
| `pc0910` | Abyss Fight Club 3 — Swiss |
| `Phantom` | Abyss Fight Club 2 — Swiss |
| `poeta` | Abyss Fight Club 3 — Swiss |
| `Putr1k3` | Abyss Fight Club 2 — Swiss |
| `qokuma` | Abyss Fight Club: Weekend 4 |
| `QQ` | Abyss Fight Club — Fast Cup 1 |
| `qqqqqbob` | Abyss Fight Club 4: Group stage 1 |
| `qryntar` | Abyss Fight Club: Abyss Weekend 5, Abyss Fight Club: Weekend 4 |
| `QSummercy` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 2 — Swiss |
| `qsummercy` | Abyss Fight Club 3 — Swiss |
| `qSummercy` | Abyss Fight Club 3 — Main Stage |
| `Reach` | Abyss Fight Club 3 — Swiss |
| `Renn` | Abyss Fight Club 2 — Swiss |
| `Reymeytil` | Abyss Fight Club 2 — Swiss |
| `rhov984` | Abyss Fight Club — Fast Cup 1 |
| `Rukaтян` | Abyss Fight Club — Fast Cup 1 |
| `S1affy` | Abyss Fight Club 2 — Swiss |
| `s1affy` | Abyss Fight Club: Weekend 3 |
| `S1kk` | Abyss Fight Club 2 — Swiss |
| `SaintPlaza` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 2 — Swiss |
| `saintplaza` | Abyss Fight Club 4: Group stage 1 |
| `Sakyra_wl` | Abyss Fight Club 2 — Swiss |
| `Sand_Witch` | Abyss Fight Club 2 — Swiss |
| `sand_witch` | Abyss Fight Club 4: Group stage 1 |
| `sasarehad` | Abyss Fight Club 4: Group stage 1 |
| `Selinq_Xd` | Abyss Fight Club 2 — Swiss |
| `Semikrit` | Abyss Fight Club 4: Group stage 1 |
| `Shu_DzY` | Abyss Fight Club 2 — Swiss |
| `Sintory` | Abyss Fight Club 2 — Main stage, Abyss Fight Club 3 — Swiss, Abyss Fight Club 2 — Swiss |
| `Skreaper` | Abyss Fight Club 2 — Swiss |
| `skreaper` | Abyss Fight Club 3 — Swiss |
| `SkyDEAD` | Abyss Fight Club 2 — Swiss |
| `Skydead` | Abyss Fight Club — Fast Cup 1 |
| `skydead15` | Abyss Fight Club: Weekend 3, Abyss Fight Club: Weekend 4 |
| `sosalov` | Abyss Fight Club: Weekend 3 |
| `sosalov1` | Abyss Fight Club: Weekend 4 |
| `Soula1r` | Abyss Fight Club 2 — Swiss |
| `Stander` | Abyss Fight Club 3 — Swiss |
| `Sterben` | Abyss Fight Club 2 — Swiss |
| `suchikama` | Abyss Fight Club: Weekend 3, Abyss Fight Club: Weekend 4 |
| `svinvinsik` | Abyss Fight Club — Fast Cup 1 |
| `swagaligator` | Abyss Fight Club: Weekend 3 |
| `TacticalNuke` | Abyss Fight Club 3 — Swiss |
| `throwdownyoursadness` | Abyss Fight Club: Weekend 4 |
| `UFO_MAN` | Abyss Fight Club 2 — Swiss |
| `Vanyyya` | Abyss Fight Club 2 — Swiss |
| `VortexShow` | Abyss Fight Club 2 — Swiss |
| `WildPanties` | Abyss Fight Club: Weekend 3, Abyss Fight Club 2 — Swiss |
| `Wnchii` | Abyss Fight Club 2 — Swiss |
| `XuShiyin许诗茵` | Abyss Fight Club — Fast Cup 1 |
| `yaeaisu` | Abyss Fight Club: Weekend 4 |
| `Yoooukii` | Abyss Fight Club 2 — Swiss |
| `ZyavaYoung` | Abyss Fight Club 2 — Swiss |
| `Æ_ARMAGEDDON` | Abyss Fight Club 3 — Swiss |
| `акаме` | Abyss Fight Club 4: Group stage 1 |
| `Кирюша Спортик` | Abyss Fight Club 2 — Swiss |
| `Личный раб` | Abyss Fight Club 2 — Swiss |
| `Меджи` | Abyss Fight Club 2 — Swiss |
| `Пупсик` | Abyss Fight Club 2 — Swiss |
| `снюся` | Abyss Fight Club — Fast Cup 1 |
| `Хорник` | Abyss Fight Club 2 — Swiss |
| `Шнобель` | Abyss Fight Club — Fast Cup 1 |
| `Щегол` | Abyss Fight Club — Fast Cup 1 |
| `Японец` | Abyss Fight Club — Fast Cup 1, Abyss Fight Club 2 — Swiss |

### 3b. В турнирах сайта (27)

Имя из сетки не найдено среди игроков этого турнира. Рядом — игроки сайта из того же турнира, которых нет в сетке: часто это один и тот же человек.

| Имя на Challonge | Турниры | Игроки сайта без пары в сетке |
|---|---|---|
| `_sunny_cat_` | Abyss Fast Soup 22 | — |
| `Akemu` | Abyss Fast Beer 2 | indepreshn |
| `Ashru` | Sovereign Eclipse | top4ik0088 |
| `Axo` | Abyss Weekend 16 | — |
| `Bliss` | Abyss New Gen 3 | king_baka |
| `chaoszks` | HotH: Abyss Weekend 11 | zks |
| `Evergarden` | Abyss Fast Soup 13 | Asyq_me, clasher_fucce |
| `EXPERT_5017` | Abyss Fast Soup 14 | clasher_fucce |
| `Gra4Serik67` | Abyss New Gen 2 | herumple, king_baka, phanora |
| `Hornick` | Women Cup | Tincan Of Meat, floriell, invidiacrystalline, pandorum, sploshnoe_otcharnie |
| `kpopium` | Abyss Weekend 14 | oujikun |
| `kravtsenok` | Women Cup | Tincan Of Meat, floriell, invidiacrystalline, pandorum, sploshnoe_otcharnie |
| `molta01` | Abyss Fast Soup 13 | Asyq_me, clasher_fucce |
| `mr.kek` | New Gen 5 Groups | indepreshn |
| `nagisa_aka_lana` | Abyss Fast Soup 13 | Asyq_me, clasher_fucce |
| `penoplllast` | Abyss Fast Soup 14 | clasher_fucce |
| `soloway` | Abyss Fast Soup 16 | soulx_9442 |
| `towakowa` | Sovereign Eclipse | top4ik0088 |
| `TPE3BOCTb` | Abyss Fast Soup 13, Abyss Fast Soup 14, Abyss New Gen 1 | Asyq_me, Caramel, HIKARU, Tricon, clasher_fucce, cori, king_baka, soulx_9442 |
| `Анелька` | Abyss New Gen 1 | Caramel, HIKARU, Tricon, clasher_fucce, cori, king_baka, soulx_9442 |
| `Банка Тушенки` | Women Cup | Tincan Of Meat, floriell, invidiacrystalline, pandorum, sploshnoe_otcharnie |
| `Ивелия` | Women Cup | Tincan Of Meat, floriell, invidiacrystalline, pandorum, sploshnoe_otcharnie |
| `Иса` | Women Cup | Tincan Of Meat, floriell, invidiacrystalline, pandorum, sploshnoe_otcharnie |
| `Одольф Клитор` | Abyss New Gen 2 | herumple, king_baka, phanora |
| `Тарас Вульва` | Abyss New Gen 1 | Caramel, HIKARU, Tricon, clasher_fucce, cori, king_baka, soulx_9442 |
| `ТЦКшник Микола` | Abyss New Gen 3 | king_baka |
| `😈темный принц😈` | HotH: Abyss Weekend 8 | oujikun |

## 4. Расхождения результатов Challonge ↔ abyss.darte

Сайт уже берёт результат из Challonge, поэтому статистика сейчас следует сетке. Ниже то, что стоит проверить у организаторов.

### Победитель на Challonge ≠ результат игр на сайте (29)

| Турнир | Матч | Подробно |
|---|---|---|
| Abyss Fast Soup 23 | `6ac13465b7ad24c6c9b3bdb3` | Baam vs DzeN: Challonge → DzeN (0:1), игры на сайте → Baam (Baam 1:DzeN 1) |
| Abyss New Gen 5 | `6aa90f3a875af1e8713f3ae3` | legangush vs rooziee: Challonge → legangush (1:0), игры на сайте → rooziee (legangush 0:rooziee 2) |
| Sovereign Eclipse | `6a79de3a95b5e77efe05eff1` | Fortik vs smertikk: Challonge → smertikk (0:0), игры на сайте → Fortik (smertikk 0:Fortik 1) |
| Sovereign Eclipse | `6a7f857395b5e77efe40956d` | smertikk vs vell1ar: Challonge → smertikk (0:0), игры на сайте → vell1ar (smertikk 0:vell1ar 1) |
| Abyss New Gen Groups | `6a664708b834541b8f1e9ff7` | Bloodfy vs tihedge: Challonge → Bloodfy (0:1), игры на сайте → tihedge (Bloodfy 1:tihedge 1) |
| Abyss New Gen Groups | `6a66471bb834541b8f1eb647` | Naa1t vs tihedge: Challonge → Naa1t (1:0), игры на сайте → tihedge (tihedge 1:Naa1t 1) |
| Abyss New Gen 3 | `6a4a23a349af709c872a9c62` | Bloodfy vs tihedge: Challonge → tihedge (0:1), игры на сайте → Bloodfy (tihedge 1:Bloodfy 1) |
| Abyss New Gen 3 | `6a45528449af709c87ead197` | clasher_fucce vs higanbana: Challonge → higanbana (0:1), игры на сайте → clasher_fucce (clasher_fucce 1:higanbana 1) |
| Abyss New Gen 3 | `6a4d502ad069d7278836d4de` | mlx vs qwebob: Challonge → qwebob (1:0), игры на сайте → mlx (mlx 1:qwebob 0) |
| Summer Quals Group E & F | `6a4548e249af709c87e873f7` | Bloodfy vs Northwar: Challonge → Northwar (0:1), игры на сайте → Bloodfy (Northwar 1:Bloodfy 1) |
| Abyss Fast Beer 3 | `6a3e54ffa2c4bbe516a393c7` | king_baka vs rooziee: Challonge → king_baka (0:1), игры на сайте → rooziee (rooziee 1:king_baka 1) |
| HotH: Abyss Weekend 13 | `6a22dad321290bc2db49aaf1` | Divizor vs vell1ar: Challonge → Divizor (0:1), игры на сайте → vell1ar (vell1ar 1:Divizor 1) |
| HotH: Abyss Weekend 13 | `6a2320dc21290bc2db4d2fda` | bestingo vs liroy: Challonge → liroy (0:1), игры на сайте → ничья (bestingo 1:liroy 1) |
| HotH: Abyss Weekend 12 | `6a0f6cecdbdcbdfd30ed2118` | Baam vs bestingo: Challonge → Baam (1:0), игры на сайте → bestingo (Baam 1:bestingo 1) |
| HotH: Abyss Weekend 12 | `6a10cae0dbdcbdfd30f61a36` | Baam vs koshmar: Challonge → koshmar (1:0), игры на сайте → Baam (koshmar 0:Baam 2) |
| HotH: Abyss Weekend 12 | `6a12fff4dbdcbdfd3009a806` | DzeN vs smertikk: Challonge → smertikk (0:1), игры на сайте → DzeN (DzeN 1:smertikk 0) |
| HotH: Abyss Weekend 12 | `6a0f6c6fdbdcbdfd30ed0c7f` | _panika_o_o vs sashakotyk: Challonge → _panika_o_o (1:0), игры на сайте → ничья (_panika_o_o 1:sashakotyk 1) |
| Abyss Ascend Admission | `69f49320dbdcbdfd301565f3` | CH1llL vs ulup: Challonge → CH1llL (0:0), игры на сайте → ulup (ulup 2:CH1llL 0) |
| Abyss Ascend Admission | `69f6e892dbdcbdfd302a500e` | ardy vs herumple: Challonge → ardy (0:0), игры на сайте → herumple (ardy 1:herumple 1) |
| Abyss Ascend Admission | `69f91310dbdcbdfd303e3893` | ardy vs koshmar: Challonge → koshmar (0:0), игры на сайте → ardy (koshmar 1:ardy 1) |
| Abyss Ascend Admission | `6a04bc0edbdcbdfd309bb805` | exelv2 vs oliverto500: Challonge → oliverto500 (0:0), игры на сайте → exelv2 (oliverto500 1:exelv2 1) |
| Abyss New Gen 2 | `69ee1326dbdcbdfd30caf864` | Abyss vs Trunkscalibur: Challonge → Trunkscalibur (0:1), игры на сайте → Abyss (Abyss 1:Trunkscalibur 1) |
| Abyss New Gen 2 | `69f22263dbdcbdfd30fe703b` | Bloodfy vs emulsiya: Challonge → Bloodfy (1:0), игры на сайте → emulsiya (Bloodfy 1:emulsiya 1) |
| Abyss Fast Soup 17 | `69ecee16dbdcbdfd30c0a633` | ardy vs oujikun: Challonge → oujikun (0:1), игры на сайте → ardy (ardy 2:oujikun 0) |
| Abyss New Gen 1 | `69c92893dbdcbdfd304ce493` | ANTOIIIKA vs siyzo: Challonge → siyzo (1053:1025), игры на сайте → ANTOIIIKA (ANTOIIIKA 1:siyzo 1) |
| Abyss New Gen 1 | `69c92d8bdbdcbdfd304d7809` | goba vs scary_booter: Challonge → scary_booter (0:0), игры на сайте → goba (scary_booter 0:goba 2) |
| Abyss New Gen 1 | `69cffd40dbdcbdfd30a14f5b` | negrisha1488 vs scary_booter: Challonge → scary_booter (1488:110), игры на сайте → negrisha1488 (negrisha1488 1:scary_booter 0) |
| Abyss Fast Soup 15 | `69c6df25fe647ab163b5ab83` | Baam vs senoen: Challonge → Baam (1:0), игры на сайте → ничья (Baam 1:senoen 1) |
| HotH: Abyss Weekend 6 | `69344cdbb79407da85c79c0d` | Divizor vs smertikk: Challonge → smertikk (519:580), игры на сайте → Divizor (Divizor 1:smertikk 0) |

### Разное число встреч одной пары (результат Challonge не применён) (4)

Пара встречалась на сайте и на Challonge разное число раз — матчи не сопоставить, решают игры на сайте.

| Турнир | Матч | Подробно |
|---|---|---|
| Sovereign Eclipse | `6a7a761c95b5e77efe0f6cc0` | bestingo vs rpyt02: на Challonge 2, на сайте 1 |
| Sovereign Eclipse | `6a8c4366875af1e871ee2289` | bestingo vs touchme: на Challonge 2, на сайте 1 |
| Abyss New Gen Groups | `6a665584b834541b8f2343e7` | crocodilo vs nnaiss: на Challonge 1, на сайте 2 |
| Abyss Cup Summer Playoff | `6a6603efb834541b8f1360fb` | Kutsuki vs peudan: на Challonge 1, на сайте 2 |

### На сайте у матча нет результата, на Challonge есть (34)

На сайте нет времени или тех. результата; победителя даёт Challonge. Обычно это неявка или незаписанное время.

| Турнир | Матч | Подробно |
|---|---|---|
| Abyss Weekend 15 | `6ab939f7875af1e8713ccf6b` | Northwar vs rpyt02: Challonge 0:1 → rpyt02 |
| Abyss Weekend 14 | `6a920227875af1e87184859d` | DzeN vs bestingo: Challonge 0:1 → DzeN |
| Abyss Weekend 14 | `6a9300d8875af1e87191139e` | Northwar vs peudan: Challonge 1:0 → Northwar |
| New Gen 5 Groups | `6a8dd102875af1e87120c5a1` | Rozax vs soulx_9442: Challonge -60:60 → Rozax |
| Sovereign Eclipse | `6a7f715795b5e77efe3f88d7` | antares377 vs vell1ar: Challonge 0:0 → vell1ar |
| Sovereign Eclipse | `6a7b5e1595b5e77efe19d1c5` | crocodilo vs goba: Challonge 0:0 → goba |
| Sovereign Eclipse | `6a7fd8d895b5e77efe438943` | qwebob vs rpyt02: Challonge 0:0 → rpyt02 |
| Abyss New Gen Groups | `6a664814b834541b8f1f22da` | Caramel vs Cazual: Challonge 1:0 → Cazual |
| Abyss New Gen Groups | `6a664c08b834541b8f20ef5c` | Lerik vs phanora: Challonge 0:1 → Lerik |
| Abyss New Gen Groups | `6a664c9fb834541b8f211f07` | Lerik vs skwardii: Challonge 0:1 → Lerik |
| Abyss New Gen 3 | `6a4551f149af709c87eaa9ec` | zertiks vs zks: Challonge 0:1 → zertiks |
| Summer Quals Group M & N | `6a45493b49af709c87e89bf0` | Fortik vs whirex.fx: Challonge 1:0 → whirex.fx |
| Abyss Fast Beer 3 | `6a3e51d5a2c4bbe516a355d8` | qwebob vs soullesswriter: Challonge 1:0 → qwebob |
| Abyss Fast Soup 19 | `6a2d93315a44a063ece1de82` | liroy vs peudan: Challonge 0:1 → peudan |
| HotH: Abyss Weekend 13 | `6a2469835a44a063ec98f1ff` | iolwann vs peudan: Challonge 1:0 → peudan |
| HotH: Abyss Weekend 13 | `6a25709d5a44a063ec9e542a` | peudan vs smertikk: Challonge 0:1 → smertikk |
| HotH: Abyss Weekend 13 | `6a231c9621290bc2db4d03c9` | smertikk vs touchme: Challonge 1:0 → smertikk |
| HotH: Abyss Weekend 12 | `6a0f6bdedbdcbdfd30ecf140` | Trunkscalibur vs koldun: Challonge 0:1 → Trunkscalibur |
| HotH: Abyss Weekend 12 | `6a1232c6dbdcbdfd3004d9b2` | senoen vs smertikk: Challonge 0:1 → smertikk |
| Abyss Ascend Admission | `69f8b724dbdcbdfd303834b3` | CH1llL vs 캐리: Challonge 0:0 → 캐리 |
| Abyss Ascend Admission | `69f72169dbdcbdfd302bbada` | Liberta vs neymiraikuriyama: Challonge 0:0 → Liberta |
| HotH: Abyss Weekend 11 | `69f6079bdbdcbdfd30237917` | peudan vs smertikk: Challonge 0:1 → peudan |
| Abyss New Gen 2 | `69ee1233dbdcbdfd30cac478` | NeGlect vs curdee: Challonge 1:0 → curdee |
| Abyss New Gen 2 | `69ee118adbdcbdfd30caaf63` | kakarikx vs youkillmydreams: Challonge 1:0 → kakarikx |
| Abyss New Gen 2 | `69ee1458dbdcbdfd30cb2518` | kolyasochnik vs ryabzyk: Challonge 0:1 → ryabzyk |
| HotH: Abyss Weekend 10 | `69db7c02dbdcbdfd30102669` | Northwar vs peudan: Challonge 0:1 → Northwar |
| HotH: Abyss Weekend 10 | `69d913ecdbdcbdfd30fe0977` | smertikk vs soulx_9442: Challonge 1:0 → smertikk |
| Abyss New Gen 1 | `69cac37ddbdcbdfd306405d4` | bestingo vs nehitomi: Challonge 612:347 → bestingo |
| HotH: Abyss Weekend 9 | `69bd2d43fe647ab16354806d` | Roro vs vell1ar: Challonge 0:1 → Roro |
| HotH: Abyss Weekend 8 | `69a3150e033f76829468622e` | Kutsuki vs Northwar: Challonge 0:1 → Kutsuki |
| HotH: Abyss Weekend 8 | `69a0a24d033f7682943c2535` | senoen vs soulx_9442: Challonge 1:0 → senoen |
| Abyss Fast Soup 13 | `699f2453033f7682941f109d` | Abyss vs snusya.228: Challonge 0:1 → Abyss |
| Abyss Fast Soup 13 | `699f2623033f7682941f7714` | Sad1n vs _panika_o_o: Challonge 1:0 → Sad1n |
| Abyss Weekend 16 | `6acbbd8aba80659ae20fb6cd` | koshmar vs rpyt02: Challonge 1:0 → rpyt02 |

### Матч есть на Challonge, но нет на сайте (344)

В основном неявки и тех. победы, проставленные только на Challonge, а также матчи игроков, которых нет в турнире на сайте.

<details><summary>Список</summary>

| Турнир | Подробно |
|---|---|
| Abyss Fast Soup 23 | Divizor vs bestingo: 1:0, победил Divizor |
| Abyss Fast Soup 23 | Northwar vs raftalia: 1:0, победил Northwar |
| Abyss Fast Soup 23 | Quiroga vs zks: 1:0, победил zks |
| Abyss Fast Soup 23 | Roro vs raftalia: 1:0, победил raftalia |
| Abyss Fast Soup 23 | Rozax vs linkle.: 1:0, победил linkle. |
| Abyss Weekend 15 | Roro vs raftalia: 0:1, победил Roro |
| Abyss Weekend 15 | kakarikx vs rpyt02: 0:1, победил rpyt02 |
| Abyss Weekend 15 | liarlialin vs shogunventi: 1:0, победил liarlialin |
| Abyss Fast Beer 4 | HIKARU vs soulx_9442: 0:1, победил HIKARU |
| Abyss Fast Beer 4 | alone vs legangush: 0:1, победил legangush |
| Abyss Fast Beer 4 | cpt.tommerhet vs herumple: 1:0, победил herumple |
| Abyss Fast Beer 4 | cpt.tommerhet vs shisui: 1:0, победил cpt.tommerhet |
| Abyss Fast Beer 4 | dud.ka vs vati: 1:0, победил vati |
| Abyss Fast Beer 4 | frogvrot vs wertmym21: 0:1, победил frogvrot |
| Abyss Fast Beer 4 | futanar1 vs rooziee: 1:0, победил rooziee |
| Abyss Fast Beer 4 | herumple vs mlx: 0:1, победил mlx |
| Abyss Fast Beer 4 | herumple vs savee13: 1:0, победил herumple |
| Abyss Fast Beer 4 | king_baka vs remission: 1:0, победил king_baka |
| Abyss Fast Beer 4 | king_baka vs vovontin: 1:0, победил king_baka |
| Abyss Fast Beer 4 | king_baka vs zks: 0:1, победил king_baka |
| Abyss Fast Beer 4 | vovontin vs ~Kelhoun..?: 0:1, победил vovontin |
| Abyss New Gen 5 | Bloodfy vs VladKvas: 0:1, победил VladKvas |
| Abyss New Gen 5 | Bloodfy vs oujikun: 0:1, победил oujikun |
| Abyss New Gen 5 | CH1llL vs frogvrot: 0:1, победил frogvrot |
| Abyss New Gen 5 | CH1llL vs savee13: 1:0, победил savee13 |
| Abyss New Gen 5 | CaPyBoBr vs liarlialin: 1:0, победил liarlialin |
| Abyss New Gen 5 | HIKARU vs crocodilo: 1:0, победил crocodilo |
| Abyss New Gen 5 | HIKARU vs tetsuyabtw: 0:1, победил tetsuyabtw |
| Abyss New Gen 5 | NeGlect vs airliok: 1:0, победил airliok |
| Abyss New Gen 5 | NeGlect vs zks: 1:0, победил zks |
| Abyss New Gen 5 | Rozax vs phanora: 0:1, победил Rozax |
| Abyss New Gen 5 | Trunkscalibur vs rooziee: 0:1, победил rooziee |
| Abyss New Gen 5 | VladKvas vs tetsuyabtw: 0:1, победил VladKvas |
| Abyss New Gen 5 | airliok vs oujikun: 0:1, победил airliok |
| Abyss New Gen 5 | frogvrot vs rooziee: 0:1, победил rooziee |
| Abyss New Gen 5 | king_baka vs zks: 0:1, победил king_baka |
| Abyss New Gen 5 | legangush vs tetsuyabtw: 1:0, победил legangush |
| Abyss New Gen 5 | mandal1n vs rooziee: 0:1, победил rooziee |
| Abyss New Gen 5 | rooziee vs zks: 1:0, победил rooziee |
| Abyss Fast Soup 22 | DzeN vs ulup: 1:0, победил ulup |
| Abyss Fast Soup 22 | bestingo vs ulup: 0:1, победил bestingo |
| Abyss Fast Soup 22 | herumple vs vell1ar: 1:0, победил vell1ar |
| Abyss Fast Soup 22 | indepreshn vs kakarikx: 1:0, победил indepreshn |
| Abyss Fast Soup 22 | liarlialin vs vell1ar: 1:0, победил vell1ar |
| Abyss Fast Soup 22 | vell1ar vs zks: 1:0, победил vell1ar |
| Abyss Weekend 14 | Baam vs rpyt02: 0:1, победил Baam |
| Abyss Weekend 14 | Baam vs smertikk: 1:0, победил smertikk |
| Abyss Weekend 14 | DzeN vs Lerik: 0:1, победил DzeN |
| Abyss Weekend 14 | Kiryu vs shogunventi: 1:0, победил shogunventi |
| Abyss Weekend 14 | Northwar vs Rer: 1:0, победил Northwar |
| Abyss Weekend 14 | Northwar vs energeqc: 1:0, победил Northwar |
| Abyss Weekend 14 | alone vs peudan: 0:1, победил peudan |
| Abyss Weekend 14 | futanar1 vs rpyt02: 1:0, победил rpyt02 |
| Abyss Weekend 14 | vapeur vs vell1ar: 1:0, победил vell1ar |
| New Gen 5 Groups | Bloodfy vs Jeank4m1k4z3: 60:-60, победил Bloodfy |
| New Gen 5 Groups | Bloodfy vs Sad1n: -60:60, победил Bloodfy |
| New Gen 5 Groups | CH1llL vs Naa1t: -60:60, победил Naa1t |
| New Gen 5 Groups | CH1llL vs chainqe.: 60:-60, победил CH1llL |
| New Gen 5 Groups | DrakeDark vs lesty21: 60:-60, победил DrakeDark |
| New Gen 5 Groups | HIKARU vs KaTletka: -60:60, победил HIKARU |
| New Gen 5 Groups | HIKARU vs phanora: -60:60, победил phanora |
| New Gen 5 Groups | KaTletka vs emulsiya: -60:60, победил emulsiya |
| New Gen 5 Groups | KaTletka vs phanora: 60:-60, победил phanora |
| New Gen 5 Groups | Naa1t vs chainqe.: -60:60, победил Naa1t |
| New Gen 5 Groups | NeGlect vs dydosik: 60:-60, победил NeGlect |
| New Gen 5 Groups | NeGlect vs mandal1n: 60:-60, победил mandal1n |
| New Gen 5 Groups | Sad1n vs crocodilo: 60:-60, победил crocodilo |
| New Gen 5 Groups | Trunkscalibur vs clasher_fucce: -60:60, победил Trunkscalibur |
| New Gen 5 Groups | Trunkscalibur vs qwaiz: 60:-60, победил Trunkscalibur |
| New Gen 5 Groups | airliok vs maktraher: -60:60, победил airliok |
| New Gen 5 Groups | antares377 vs lesty21: 60:-60, победил antares377 |
| New Gen 5 Groups | chainqe. vs wertmym21: -60:60, победил wertmym21 |
| New Gen 5 Groups | clasher_fucce vs goba: 60:-60, победил goba |
| New Gen 5 Groups | clasher_fucce vs qwaiz: -60:60, победил clasher_fucce |
| New Gen 5 Groups | emulsiya vs roulix: -60:60, победил emulsiya |
| New Gen 5 Groups | energeqc vs wertmym21: -60:60, победил energeqc |
| New Gen 5 Groups | frogvrot vs savee13: -60:60, победил savee13 |
| New Gen 5 Groups | funtik vs qwaiz: 60:-60, победил funtik |
| New Gen 5 Groups | goba vs qwaiz: -60:60, победил goba |
| New Gen 5 Groups | lin_lin_ vs soulx_9442: 60:-60, победил lin_lin_ |
| New Gen 5 Groups | maktraher vs rooziee: -60:60, победил rooziee |
| New Gen 5 Groups | phanora vs roulix: 60:-60, победил phanora |
| New Gen 5 Groups | savee13 vs ximonstar: -60:60, победил savee13 |
| New Gen 5 Groups | serenad vs zks: -60:60, победил zks |
| New Gen 5 Groups | ulup vs ximonstar: 60:-60, победил ulup |
| Sovereign Eclipse | CH1llL vs Merlot: 0:0, победил CH1llL |
| Sovereign Eclipse | CH1llL vs vell1ar: 0:0, победил vell1ar |
| Sovereign Eclipse | Divizor vs rpyt02: 0:0, победил rpyt02 |
| Sovereign Eclipse | Divizor vs smertikk: 0:0, победил smertikk |
| Sovereign Eclipse | Merlot vs touchme: 0:0, победил touchme |
| Sovereign Eclipse | Naa1t vs antares377: 0:0, победил antares377 |
| Sovereign Eclipse | Pmir vs koshmar: 0:0, победил koshmar |
| Sovereign Eclipse | Pmir vs rpyt02: 0:0, победил rpyt02 |
| Sovereign Eclipse | Traventer vs raftalia: 0:0, победил Traventer |
| Sovereign Eclipse | alone vs qwebob: 0:0, победил qwebob |
| Sovereign Eclipse | alone vs vell1ar: 0:0, победил vell1ar |
| Sovereign Eclipse | antares377 vs wertmym21: 0:0, победил wertmym21 |
| Sovereign Eclipse | bestingo vs kakarikx: 0:0, победил bestingo |
| Sovereign Eclipse | bestingo vs koshmar: 0:0, победил bestingo |
| Sovereign Eclipse | bestingo vs oujikun: 0:0, победил bestingo |
| Sovereign Eclipse | frogvrot vs raftalia: 0:0, победил frogvrot |
| Sovereign Eclipse | kisselka vs rpyt02: 0:0, победил rpyt02 |
| Sovereign Eclipse | koshmar vs touchme: 0:0, победил koshmar |
| Sovereign Eclipse | oujikun vs smertikk: 0:0, победил oujikun |
| Sovereign Eclipse | qwebob vs touchme: 0:0, победил touchme |
| Sovereign Eclipse | touchme vs vell1ar: 0:0, победил touchme |
| Abyss New Gen 4 | Caramel vs Lerik: 0:1, победил Caramel |
| Abyss New Gen 4 | Caramel vs legangush: 0:1, победил legangush |
| Abyss New Gen 4 | VladKvas vs goba: 0:1, победил VladKvas |
| Abyss New Gen 4 | kakarikx vs mlx: 1:0, победил kakarikx |
| Abyss New Gen Groups | Caramel vs Hevix: 0:0, победил Caramel |
| Abyss New Gen Groups | Cazual vs Hevix: 0:0, победил Cazual |
| Abyss New Gen Groups | Headovka vs Lerik: 1:0, победил Lerik |
| Abyss New Gen Groups | Headovka vs phanora: 0:1, победил phanora |
| Abyss New Gen Groups | Headovka vs skwardii: 0:1, победил skwardii |
| Abyss New Gen Groups | Hevix vs _panika_o_o: 0:0, победил _panika_o_o |
| Abyss New Gen Groups | Sky_SIJla vs alone: 0:0, победил alone |
| Abyss New Gen Groups | Sky_SIJla vs goba: 0:1, победил goba |
| Abyss New Gen Groups | Sky_SIJla vs mlx: 0:0, победил mlx |
| Abyss New Gen Groups | astro_liber vs frogvrot: 0:1, победил astro_liber |
| Abyss New Gen Groups | crocodilo vs vvvgg80: 0:1, победил crocodilo |
| Abyss New Gen Groups | forttressor00 vs frogvrot: 1:0, победил forttressor00 |
| Abyss New Gen Groups | funtik vs wertmym21: 1:0, победил funtik |
| Abyss New Gen Groups | legangush vs wertmym21: 0:0, победил legangush |
| Abyss Fast Soup 21 | Pmir vs oujikun: 0:1, победил Pmir |
| Abyss Fast Soup 21 | bestingo vs futanar1: 0:1, победил bestingo |
| Summer Quals 2nd Stage Group G & H | DzeN vs koldun: 0:1, победил DzeN |
| Summer Quals 2nd Stage Group E & F | Kutsuki vs jubes_: 0:1, победил Kutsuki |
| Summer Quals 2nd Stage Group E & F | jubes_ vs tihedge: 1:0, победил tihedge |
| Summer Quals 2nd Stage Group C & D | Rosh vs besforu: 1:0, победил besforu |
| Summer Quals 2nd Stage Group C & D | koshmar vs savee13: 0:1, победил koshmar |
| Summer Quals 2nd Stage Group A & B | Pmir vs SelfishRift: 1:0, победил Pmir |
| Abyss New Gen 3 | 2_4_8 vs savee13: 0:1, победил savee13 |
| Abyss New Gen 3 | CaPyBoBr vs lin_lin_: 1:0, победил lin_lin_ |
| Abyss New Gen 3 | HIKARU vs kakarikx: 1:0, победил kakarikx |
| Abyss New Gen 3 | HIKARU vs savee13: 1:0, победил savee13 |
| Abyss New Gen 3 | HIKARU vs zks: 1:0, победил HIKARU |
| Abyss New Gen 3 | Naa1t vs VladKvas: 1:0, победил VladKvas |
| Abyss New Gen 3 | NeGlect vs maudsoy: 1:0, победил NeGlect |
| Abyss New Gen 3 | NeGlect vs phanora: 0:1, победил NeGlect |
| Abyss New Gen 3 | NeGlect vs zertiks: 0:1, победил zertiks |
| Abyss New Gen 3 | Rozax vs VladKvas: 0:1, победил Rozax |
| Abyss New Gen 3 | Rozax vs roulix: 1:0, победил Rozax |
| Abyss New Gen 3 | Traventer vs antares377: 1:0, победил antares377 |
| Abyss New Gen 3 | Trunkscalibur vs futanar1: 0:1, победил futanar1 |
| Abyss New Gen 3 | VladKvas vs neymiraikuriyama: 1:0, победил VladKvas |
| Abyss New Gen 3 | _panika_o_o vs mlx: 1:0, победил mlx |
| Abyss New Gen 3 | alone vs nehitomi: 0:1, победил nehitomi |
| Abyss New Gen 3 | besforu vs wertmym21: 0:1, победил besforu |
| Abyss New Gen 3 | frogvrot vs phanora: 0:1, победил frogvrot |
| Abyss New Gen 3 | lin_lin_ vs savee13: 0:1, победил savee13 |
| Abyss New Gen 3 | mihayes vs nehitomi: 1:0, победил mihayes |
| Abyss New Gen 3 | nehitomi vs rudyy_nothehe: 1:0, победил nehitomi |
| Abyss New Gen 3 | nnaiss vs tihedge: 1:0, победил tihedge |
| Abyss New Gen 3 | nnaiss vs wertmym21: 0:1, победил nnaiss |
| Abyss New Gen 3 | tihedge vs zertiks: 0:1, победил zertiks |
| Summer Quals Group O & P | futanar1 vs touchme: 1:0, победил touchme |
| Summer Quals Group M & N | jaba_jab vs peudan: 0:1, победил peudan |
| Summer Quals Group K & L | Kazax vs Rosh: 0:1, победил Rosh |
| Summer Quals Group K & L | Kazax vs kurei: 1:0, победил kurei |
| Summer Quals Group K & L | king_baka vs soullesswriter: 0:1, победил soullesswriter |
| Summer Quals Group I & J | mlx vs soulx_9442: 1:0, победил soulx_9442 |
| Summer Quals Group I & J | smertikk vs soulx_9442: 0:1, победил smertikk |
| Summer Quals Group G & H | lin_lin_ vs rpyt02: 1:0, победил rpyt02 |
| Summer Quals Group C & D | SelfishRift vs antares377: 0:1, победил SelfishRift |
| Summer Quals Group A & B | oujikun vs qwebob: 1:0, победил oujikun |
| Abyss Fast Beer 3 | Arcanum vs tcat: 0:1, победил Arcanum |
| Abyss Fast Beer 3 | CH1llL vs funtik: 0:1, победил funtik |
| Abyss Fast Beer 3 | Malrois vs soullesswriter: 0:1, победил soullesswriter |
| Abyss Fast Beer 3 | Traventer vs scimitron: 1:0, победил Traventer |
| Abyss Fast Beer 3 | alone vs futanar1: 1:0, победил futanar1 |
| Abyss Fast Beer 3 | higanbana vs roulix: 0:1, победил higanbana |
| Abyss Fast Beer 3 | higanbana vs tetsuyabtw: 0:1, победил higanbana |
| Abyss Fast Beer 3 | lin_lin_ vs wertmym21: 1:0, победил wertmym21 |
| Abyss Fast Beer 3 | maudsoy vs wertmym21: 1:0, победил maudsoy |
| Abyss Fast Beer 3 | nnaiss vs zks: 0:1, победил nnaiss |
| Abyss Fast Soup 20 | Baam vs peudan: 0:1, победил peudan |
| Abyss Fast Soup 20 | Divizor vs soulx_9442: 0:1, победил Divizor |
| Abyss Fast Soup 20 | DzeN vs Pmir: 0:1, победил DzeN |
| Abyss Fast Soup 20 | Rozax vs peudan: 1:0, победил peudan |
| Abyss Fast Soup 19 | Divizor vs Neko_Asase: 1:0, победил Divizor |
| Abyss Fast Soup 19 | HIKARU vs Rer: 0:1, победил Rer |
| Abyss Fast Soup 19 | Kutsuki vs bestingo: 1:0, победил Kutsuki |
| Abyss Fast Soup 19 | alone vs smertikk: 1:0, победил smertikk |
| Abyss Fast Soup 19 | crocodilo vs linkle.: 0:1, победил crocodilo |
| Abyss Fast Soup 19 | lin_lin_ vs zks: 1:0, победил zks |
| HotH: Abyss Weekend 13 | Kutsuki vs liroy: 1:0, победил liroy |
| HotH: Abyss Weekend 13 | Roro vs crocodilo: 1:0, победил crocodilo |
| HotH: Abyss Weekend 13 | alone vs zks: 1:0, победил zks |
| HotH: Abyss Weekend 13 | herumple vs liarlialin: 1:0, победил liarlialin |
| HotH: Abyss Weekend 13 | liroy vs peudan: 1:0, победил peudan |
| Abyss Fast Soup 18 | Baam vs HIKARU: 0:1, победил Baam |
| Abyss Fast Soup 18 | smertikk vs wertmym21: 0:1, победил smertikk |
| HotH: Abyss Weekend 12 | Rer vs soulx_9442: 1:0, победил Rer |
| HotH: Abyss Weekend 12 | herumple vs liarlialin: 1:0, победил liarlialin |
| HotH: Abyss Weekend 12 | koshmar vs kurei: 1:0, победил koshmar |
| HotH: Abyss Weekend 12 | liarlialin vs vell1ar: 0:1, победил liarlialin |
| HotH: Abyss Weekend 12 | mandal1n vs phanora: 1:0, победил mandal1n |
| HotH: Abyss Weekend 12 | mandal1n vs vell1ar: 1:0, победил vell1ar |
| Abyss Fast Beer 2 | CH1llL vs crocodilo: 0:1, победил crocodilo |
| Abyss Fast Beer 2 | Caramel vs herumple: 1:0, победил herumple |
| Abyss Fast Beer 2 | Kazax vs soullesswriter: 1:0, победил soullesswriter |
| Abyss Fast Beer 2 | Lerik vs airliok: 0:1, победил airliok |
| Abyss Fast Beer 2 | besforu vs rudyy_nothehe: 1:0, победил besforu |
| Abyss Fast Beer 2 | besforu vs zks: 1:0, победил besforu |
| Abyss Fast Beer 2 | bestingo vs phanora: 1:0, победил bestingo |
| Abyss Fast Beer 2 | legangush vs snusya.228: 0:1, победил legangush |
| Abyss Ascend Admission | Divizor vs curdee: 0:0, победил Divizor |
| Abyss Ascend Admission | Divizor vs liroy: 0:0, победил liroy |
| Abyss Ascend Admission | Liberta vs oliverto500: 0:0, победил Liberta |
| Abyss Ascend Admission | Merlot vs Roro: 0:0, победил Merlot |
| Abyss Ascend Admission | Pr0metheus vs koshmar: 0:0, победил koshmar |
| Abyss Ascend Admission | bestingo vs liroy: 0:0, победил liroy |
| Abyss Ascend Admission | exelv2 vs kinimeshka: 0:0, победил exelv2 |
| Abyss Ascend Admission | koshmar vs liroy: 0:0, победил liroy |
| Abyss Ascend Admission | lifelong vs qwaiz: 0:0, победил lifelong |
| HotH: Abyss Weekend 11 | Baam vs CH1llL: 1:0, победил CH1llL |
| HotH: Abyss Weekend 11 | CH1llL vs senoen: 1:0, победил senoen |
| HotH: Abyss Weekend 11 | Divizor vs rpyt02: 1:0, победил rpyt02 |
| HotH: Abyss Weekend 11 | Kutsuki vs peudan: 1:0, победил peudan |
| HotH: Abyss Weekend 11 | chainqe. vs liroy: 1:0, победил liroy |
| HotH: Abyss Weekend 11 | herumple vs peudan: 1:0, победил peudan |
| HotH: Abyss Weekend 11 | liroy vs vell1ar: 0:1, победил liroy |
| HotH: Abyss Weekend 11 | oliverto500 vs vell1ar: 1:0, победил vell1ar |
| HotH: Abyss Weekend 11 | peudan vs senoen: 1:0, победил peudan |
| Abyss New Gen 2 | 2_4_8 vs exarcise: 1:0, победил 2_4_8 |
| Abyss New Gen 2 | 2_4_8 vs neymiraikuriyama: 0:1, победил neymiraikuriyama |
| Abyss New Gen 2 | 2_4_8 vs roulix: 0:1, победил 2_4_8 |
| Abyss New Gen 2 | Azimontias vs dydosik: 0:1, победил dydosik |
| Abyss New Gen 2 | Caramel vs VladKvas: 1:0, победил VladKvas |
| Abyss New Gen 2 | Headovka vs bestingo: 0:1, победил Headovka |
| Abyss New Gen 2 | Kazax vs soulx_9442: 0:1, победил soulx_9442 |
| Abyss New Gen 2 | Michisaurio vs curdee: 0:1, победил curdee |
| Abyss New Gen 2 | Michisaurio vs ulup: 0:1, победил ulup |
| Abyss New Gen 2 | NeGlect vs rudyy_nothehe: 1:0, победил rudyy_nothehe |
| Abyss New Gen 2 | Sad1n vs forttressor00: 1:0, победил forttressor00 |
| Abyss New Gen 2 | Sad1n vs futanar1: 0:1, победил futanar1 |
| Abyss New Gen 2 | Sad1n vs ximonstar: 1:0, победил Sad1n |
| Abyss New Gen 2 | besforu vs extremefine0: 0:1, победил besforu |
| Abyss New Gen 2 | bestingo vs cap1sha1: 1:0, победил bestingo |
| Abyss New Gen 2 | bestingo vs ulup: 0:1, победил ulup |
| Abyss New Gen 2 | clasher_fucce vs exarcise: 0:1, победил clasher_fucce |
| Abyss New Gen 2 | clasher_fucce vs legangush: 1:0, победил legangush |
| Abyss New Gen 2 | crocodilo vs dydosik: 1:0, победил crocodilo |
| Abyss New Gen 2 | dydosik vs roulix: 0:1, победил dydosik |
| Abyss New Gen 2 | frogvrot vs koldun: 1:0, победил koldun |
| Abyss New Gen 2 | frogvrot vs savee13: 0:1, победил savee13 |
| Abyss New Gen 2 | koldun vs ulup: 1:0, победил koldun |
| Abyss New Gen 2 | lin_lin_ vs neymiraikuriyama: 1:0, победил lin_lin_ |
| Abyss New Gen 2 | lin_lin_ vs savee13: 0:1, победил savee13 |
| Abyss New Gen 2 | rudyy_nothehe vs ryabzyk: 0:1, победил rudyy_nothehe |
| Abyss Fast Soup 17 | Baam vs Kutsuki: 0:1, победил Kutsuki |
| Abyss Fast Soup 17 | Neko_Asase vs smertikk: 1:0, победил smertikk |
| Abyss Fast Soup 17 | Pmir vs peudan: 1:0, победил peudan |
| Abyss Fast Soup 17 | bestingo vs herumple: 1:0, победил herumple |
| Abyss Fast Soup 17 | oujikun vs senoen: 0:1, победил senoen |
| Abyss Fast Soup 17 | peudan vs soulx_9442: 1:0, победил peudan |
| HotH: Abyss Weekend 10 | DzeN vs liarlialin: 0:1, победил DzeN |
| HotH: Abyss Weekend 10 | DzeN vs oujikun: 0:1, победил DzeN |
| HotH: Abyss Weekend 10 | Northwar vs Rer: 0:1, победил Rer |
| HotH: Abyss Weekend 10 | Pmir vs rpyt02: 0:1, победил Pmir |
| HotH: Abyss Weekend 10 | Rer vs koshmar: 1:0, победил Rer |
| HotH: Abyss Weekend 10 | Rer vs vell1ar: 1:0, победил Rer |
| HotH: Abyss Weekend 10 | herumple vs koshmar: 1:0, победил koshmar |
| HotH: Abyss Weekend 10 | mina_rdm vs rpyt02: 1:0, победил rpyt02 |
| HotH: Abyss Weekend 10 | solohoneygoose vs soulx_9442: 0:1, победил soulx_9442 |
| Abyss Fast Soup 16 | Deux vs shogunventi: 0:1, победил shogunventi |
| Abyss Fast Soup 16 | Northwar vs senoen: 0:1, победил Northwar |
| Abyss Fast Soup 16 | Trunkscalibur vs finik: 1:0, победил Trunkscalibur |
| Abyss Fast Soup 16 | blackcatten vs siyzo: 1:0, победил blackcatten |
| Abyss New Gen 1 | 2_4_8 vs mandal1n: 0:1, победил mandal1n |
| Abyss New Gen 1 | ANTOIIIKA vs emulsiya: 0:0, победил emulsiya |
| Abyss New Gen 1 | Kiyota vs Rozax: 0:0, победил Rozax |
| Abyss New Gen 1 | Kiyota vs alone: 389:900, победил alone |
| Abyss New Gen 1 | Lerik vs SOBAKEN: 0:0, победил SOBAKEN |
| Abyss New Gen 1 | Lerik vs kakarikx: 0:0, победил Lerik |
| Abyss New Gen 1 | Lerik vs kolyasochnik: 0:0, победил Lerik |
| Abyss New Gen 1 | Noteflight vs roulix: 0:0, победил Noteflight |
| Abyss New Gen 1 | Rozax vs oujikun: 280:267, победил oujikun |
| Abyss New Gen 1 | Rozax vs phanora: 0:0, победил Rozax |
| Abyss New Gen 1 | Sky_SIJla vs wertmym21: 425:321, победил wertmym21 |
| Abyss New Gen 1 | VladKvas vs fateeb: 231:0, победил VladKvas |
| Abyss New Gen 1 | VladKvas vs lin_lin_: 369:384, победил lin_lin_ |
| Abyss New Gen 1 | alone vs mandal1n: 0:1, победил mandal1n |
| Abyss New Gen 1 | dench1kehNut vs mihayes: 0:0, победил mihayes |
| Abyss New Gen 1 | ghost_loyzNut vs lin_lin_: 0:0, победил lin_lin_ |
| Abyss New Gen 1 | ghost_loyzNut vs nehitomi: 465:581, победил ghost_loyzNut |
| Abyss New Gen 1 | herumple vs wanar1n: 0:0, победил herumple |
| Abyss New Gen 1 | kiisllottaNut vs negrisha1488: 0:0, победил negrisha1488 |
| Abyss New Gen 1 | kolyasochnik vs shogunventi: 0:0, победил shogunventi |
| Abyss New Gen 1 | mandal1n vs wertmym21: 784:81, победил mandal1n |
| Abyss New Gen 1 | mandal1n vs zertiks: 0:0, победил mandal1n |
| Abyss New Gen 1 | phanora vs wanar1n: 0:0, победил phanora |
| Abyss New Gen 1 | phanora vs wertmym21: 752:192, победил wertmym21 |
| Abyss Fast Soup 15 | Deux vs finik: 1:0, победил finik |
| Abyss Fast Soup 15 | P2SHOCK vs Sad1n: 0:1, победил P2SHOCK |
| Abyss Fast Soup 15 | goba vs senoen: 0:1, победил senoen |
| HotH: Abyss Weekend 9 | Baam vs smertikk: 1:0, победил Baam |
| HotH: Abyss Weekend 9 | Kutsuki vs Northwar: 0:1, победил Kutsuki |
| HotH: Abyss Weekend 9 | Kutsuki vs Pmir: 1:0, победил Kutsuki |
| HotH: Abyss Weekend 9 | Kutsuki vs peudan: 1:0, победил Kutsuki |
| HotH: Abyss Weekend 9 | Pmir vs kurei: 1:0, победил Pmir |
| HotH: Abyss Weekend 9 | Pmir vs linkle.: 0:0, победил Pmir |
| HotH: Abyss Weekend 9 | Pmir vs solohoneygoose: 0:1, победил Pmir |
| Abyss Fast Soup 14 | Dark vs cap1sha1: 0:1, победил Dark |
| Abyss Fast Soup 14 | Northwar vs bestingo: 1:0, победил Northwar |
| Abyss Fast Soup 14 | Rer vs Roro: 1:0, победил Roro |
| Abyss Fast Soup 14 | Roro vs top4ik0088: 1:0, победил Roro |
| Abyss Fast Soup 14 | ardy vs younitor: 1:0, победил ardy |
| Abyss Fast Soup 14 | koshmar vs liroy: 0:1, победил liroy |
| Abyss Fast Soup 14 | kurei vs smertikk: 1:0, победил smertikk |
| HotH: Abyss Weekend 8 | Baam vs vell1ar: 1:0, победил vell1ar |
| HotH: Abyss Weekend 8 | Caramel vs rpyt02: 1:0, победил rpyt02 |
| HotH: Abyss Weekend 8 | Divizor vs liarlialin: 1:0, победил liarlialin |
| HotH: Abyss Weekend 8 | Kutsuki vs linkle.: 1:0, победил linkle. |
| HotH: Abyss Weekend 8 | Rer vs raftalia: 0:1, победил Rer |
| HotH: Abyss Weekend 8 | Roro vs koshmar: 0:0, победил koshmar |
| HotH: Abyss Weekend 8 | alone vs peudan: 0:1, победил peudan |
| HotH: Abyss Weekend 8 | koshmar vs kurei: 0:1, победил koshmar |
| HotH: Abyss Weekend 8 | linkle. vs senoen: 1:0, победил linkle. |
| Abyss Fast Soup 13 | Abyss vs energeqc: 1:0, победил energeqc |
| Abyss Fast Soup 13 | Baam vs Cazual: 1:0, победил Baam |
| Abyss Fast Soup 13 | Deux vs vati: 1:0, победил vati |
| Abyss Fast Soup 13 | YoungReezy vs top4ik0088: 1:0, победил YoungReezy |
| Abyss Fast Soup 13 | colldd vs soullesswriter: 0:1, победил soullesswriter |
| Abyss Fast Soup 13 | inquisitor1001 vs shogunventi: 1:0, победил shogunventi |
| Abyss Fast Soup 13 | jaba_jab vs yu: 0:1, победил jaba_jab |
| Abyss Fast Soup 13 | kurei vs mandal1n: 0:1, победил mandal1n |
| Abyss Fast Soup 13 | legangush vs vati: 1:0, победил legangush |
| Abyss Fast Soup 13 | lin_lin_ vs mandal1n: 0:1, победил mandal1n |
| Abyss Fast Soup 13 | oujikun vs traizzxq: 1:0, победил oujikun |
| Abyss Weekend 16 | Baam vs Rer: 0:1, победил Baam |
| Abyss Weekend 16 | Divizor vs frogvrot: 0:1, победил Divizor |
| Abyss Weekend 16 | _panika_o_o vs qwebob: 1:0, победил qwebob |
| Abyss Weekend 16 | crocodilo vs nnaiss: 0:1, победил nnaiss |
| Abyss Weekend 16 | raftalia vs smertikk: 1:0, победил smertikk |
| Abyss Weekend 16 | shogunventi vs vell1ar: 0:1, победил shogunventi |
| HotH: Abyss Weekend 6 | Northwar vs Roro: 0:0, победил Northwar |
| HotH: Abyss Weekend 6 | Northwar vs antares377: 0:0, победил Northwar |
| HotH: Abyss Weekend 6 | Northwar vs futanar1: 0:0, победил Northwar |
| HotH: Abyss Weekend 6 | Northwar vs smertikk: 0:0, победил Northwar |
| HotH: Abyss Weekend 6 | Sombraro vs liarlialin: 0:0, победил liarlialin |
| HotH: Abyss Weekend 6 | liarlialin vs rpyt02: 0:0, победил rpyt02 |
| HotH: Abyss Weekend 6 | lmao vs raftalia: 0:0, победил raftalia |

</details>

### Матч есть на сайте, но нет на Challonge (74)

Обычно матч с игроком, чьё имя в сетке не сопоставлено (см. раздел 3b), или переигровка.

<details><summary>Список</summary>

| Турнир | Подробно |
|---|---|
| Abyss Weekend 14 | bestingo vs oujikun: oujikun 0:bestingo 0 · `6a90b318875af1e8716746f2` |
| New Gen 5 Groups | indepreshn vs legangush: indepreshn 0:legangush 2 · `6a8dd189875af1e87120ff00` |
| New Gen 5 Groups | indepreshn vs mlx: mlx 1:indepreshn 0 · `6a8dd39c875af1e871223468` |
| New Gen 5 Groups | indepreshn vs tetsuyabtw: indepreshn 0:tetsuyabtw 1 · `6a8f0d59875af1e871412584` |
| Sovereign Eclipse | herumple vs top4ik0088: top4ik0088 0:herumple 1 · `6a79d61895b5e77efe05594a` |
| Abyss New Gen 4 | Bloodfy vs king_baka: Bloodfy 1:king_baka 1 · `6a789942b834541b8f523ce2` |
| Abyss New Gen 4 | astro_liber vs king_baka: astro_liber 2:king_baka 0 · `6a721c35b834541b8fedf6dd` |
| Abyss New Gen 4 | crocodilo vs king_baka: king_baka 1:crocodilo 1 · `6a762a0bb834541b8f30ca26` |
| Abyss New Gen Groups | crocodilo vs king_baka: crocodilo 0:king_baka 2 · `6a664b05b834541b8f2070eb` |
| Abyss New Gen Groups | crocodilo vs king_baka: king_baka 1:crocodilo 1 · `6a6f8d14b834541b8fc298bf` |
| Abyss New Gen Groups | king_baka vs nnaiss: nnaiss 1:king_baka 1 · `6a665595b834541b8f234d08` |
| Abyss New Gen Groups | king_baka vs nnaiss: nnaiss 1:king_baka 1 · `6a6f3e68b834541b8fbb00ba` |
| Abyss New Gen 3 | kakarikx vs king_baka: kakarikx 1:king_baka 1 · `6a4e8106d069d727883e8508` |
| Abyss New Gen 3 | king_baka vs mihayes: king_baka 2:mihayes 0 · `6a49194c49af709c871c078c` |
| Women Cup | Hevix vs floriell: floriell 0:Hevix 2 · `6a35921e09e09ea6bc2f6d05` |
| Women Cup | NeGlect vs pandorum: NeGlect 2:pandorum 0 · `6a359d6e09e09ea6bc30ae59` |
| Women Cup | NeGlect vs sploshnoe_otcharnie: NeGlect 2:sploshnoe_otcharnie 0 · `6a366e5909e09ea6bc37ddc0` |
| Women Cup | Tincan Of Meat vs sploshnoe_otcharnie: Tincan Of Meat 0:sploshnoe_otcharnie 2 · `6a3557a709e09ea6bc298e03` |
| Women Cup | floriell vs invidiacrystalline: invidiacrystalline 1:floriell 1 · `6a3469c709e09ea6bc1e9304` |
| HotH: Abyss Weekend 12 | HIKARU vs Roro: HIKARU 0:Roro 2 · `6a0f67c9dbdcbdfd30ecbeb0` |
| Abyss Fast Beer 2 | hanka vs indepreshn: hanka 0:indepreshn 2 · `69fcbb26dbdcbdfd3060266b` |
| Abyss Fast Beer 2 | indepreshn vs siyzo: indepreshn 0:siyzo 2 · `69fe1755dbdcbdfd3071e568` |
| HotH: Abyss Weekend 11 | smertikk vs zks: smertikk 1:zks 1 · `69f3c099dbdcbdfd3010368d` |
| Abyss New Gen 2 | Bloodfy vs herumple: Bloodfy 1:herumple 1 · `69f0c00cdbdcbdfd30e78190` |
| Abyss New Gen 2 | Headovka vs king_baka: king_baka 2:Headovka 0 · `69f9cec8dbdcbdfd3042a9b5` |
| Abyss New Gen 2 | Noteflight vs phanora: Noteflight 0:phanora 2 · `69f10abedbdcbdfd30f16ba8` |
| Abyss New Gen 2 | Sad1n vs phanora: Sad1n 0:phanora 2 · `69ee11ffdbdcbdfd30cab901` |
| Abyss New Gen 2 | energeqc vs herumple: energeqc 0:herumple 2 · `69fa39abdbdcbdfd3049e54a` |
| Abyss New Gen 2 | energeqc vs king_baka: king_baka 1:energeqc 1 · `69ffcc55dbdcbdfd307fea10` |
| Abyss New Gen 2 | futanar1 vs king_baka: king_baka 1:futanar1 1 · `69fb652bdbdcbdfd30545d29` |
| Abyss New Gen 2 | herumple vs king_baka: herumple 2:king_baka 0 · `69f39a72dbdcbdfd300dbbd6` |
| Abyss New Gen 2 | herumple vs mandal1n: herumple 1:mandal1n 1 · `6a0230dedbdcbdfd309005d3` |
| Abyss New Gen 2 | herumple vs mandal1n: herumple 2:mandal1n 0 · `6a076277dbdcbdfd30a52dda` |
| Abyss New Gen 2 | king_baka vs legangush: legangush 0:king_baka 2 · `69f8e8c6dbdcbdfd303bb5df` |
| Abyss New Gen 2 | king_baka vs ulup: ulup 0:king_baka 2 · `69ee0fd7dbdcbdfd30ca833d` |
| Abyss New Gen 2 | king_baka vs zks: king_baka 1:zks 1 · `69f63a55dbdcbdfd3026ae54` |
| Abyss New Gen 2 | neymiraikuriyama vs phanora: phanora 0:neymiraikuriyama 2 · `69f12045dbdcbdfd30f3aa7a` |
| Abyss Fast Soup 16 | Naa1t vs soulx_9442: Naa1t 1:soulx_9442 1 · `69cea5acdbdcbdfd30925f45` |
| Abyss New Gen 1 | CaPyBoBr vs king_baka: CaPyBoBr 0:king_baka 2 · `69d00467dbdcbdfd30a21433` |
| Abyss New Gen 1 | Caramel vs Merlot: Caramel 2:Merlot 0 · `69cad72cdbdcbdfd30670681` |
| Abyss New Gen 1 | Caramel vs kakarikx: kakarikx 2:Caramel 0 · `69c929c1dbdcbdfd304d00c9` |
| Abyss New Gen 1 | Caramel vs scary_booter: Caramel 0:scary_booter 2 · `69d25275dbdcbdfd30bd343e` |
| Abyss New Gen 1 | Dark vs HIKARU: Dark 1:HIKARU 1 · `69d22309dbdcbdfd30baf8f5` |
| Abyss New Gen 1 | HIKARU vs Sky_SIJla: HIKARU 1:Sky_SIJla 1 · `69cd0b5edbdcbdfd30816eea` |
| Abyss New Gen 1 | HIKARU vs crocodilo: HIKARU 0:crocodilo 2 · `69c92cf3dbdcbdfd304d5aed` |
| Abyss New Gen 1 | Marker vs Tricon: Marker 1:Tricon 1 · `69cb6398dbdcbdfd306c7170` |
| Abyss New Gen 1 | Noteflight vs cori: cori 0:Noteflight 2 · `69c99176dbdcbdfd30560a06` |
| Abyss New Gen 1 | Sad1n vs clasher_fucce: Sad1n 1:clasher_fucce 1 · `69cbe49ddbdcbdfd3072c736` |
| Abyss New Gen 1 | clasher_fucce vs soulx_9442: soulx_9442 2:clasher_fucce 0 · `69cd5bf4dbdcbdfd30862958` |
| Abyss New Gen 1 | clasher_fucce vs traizzxq: traizzxq 2:clasher_fucce 0 · `69c92dd5dbdcbdfd304d87b9` |
| Abyss New Gen 1 | cori vs youkillmydreams: youkillmydreams 2:cori 0 · `69c928f5dbdcbdfd304cef3b` |
| Abyss New Gen 1 | goba vs soulx_9442: soulx_9442 0:goba 2 · `69d0063edbdcbdfd30a26403` |
| Abyss New Gen 1 | herumple vs king_baka: herumple 1:king_baka 1 · `69d56d8bdbdcbdfd30def8f6` |
| Abyss New Gen 1 | kiisllottaNut vs soulx_9442: kiisllottaNut 1:soulx_9442 1 · `69c92afadbdcbdfd304d231d` |
| Abyss New Gen 1 | king_baka vs mandal1n: king_baka 0:mandal1n 2 · `69d7d80cdbdcbdfd30f085fd` |
| Abyss New Gen 1 | king_baka vs oliverto500: oliverto500 1:king_baka 1 · `69d2525edbdcbdfd30bd30fb` |
| Abyss New Gen 1 | king_baka vs roulix: roulix 0:king_baka 2 · `69c92916dbdcbdfd304cf321` |
| Abyss New Gen 1 | king_baka vs youkillmydreams: youkillmydreams 0:king_baka 2 · `69c972dcdbdcbdfd3053e904` |
| Abyss New Gen 1 | savee13 vs soulx_9442: soulx_9442 0:savee13 2 · `69cacc44dbdcbdfd3065b086` |
| Abyss Fast Soup 15 | Divizor vs soulx_9442: soulx_9442 0:Divizor 2 · `69c56f25fe647ab163a4971e` |
| HotH: Abyss Weekend 9 | HIKARU vs Rer: HIKARU 0:Rer 2 · `69bd2c11fe647ab163546bcb` |
| Abyss Fast Soup 14 | clasher_fucce vs mandal1n: mandal1n 2:clasher_fucce 0 · `69a9c4d0033f768294b8ec94` |
| HotH: Abyss Weekend 8 | Lerik vs oujikun: Lerik 0:oujikun 2 · `69a0a333033f7682943c626f` |
| Abyss Fast Soup 13 | Asyq_me vs besforu: besforu 2:Asyq_me 0 · `699f23c4033f7682941ee3b1` |
| Abyss Fast Soup 13 | clasher_fucce vs twelf: twelf 1:clasher_fucce 1 · `699f258e033f7682941f5977` |
| HotH: Abyss Weekend 7 | Baam vs herumple: herumple 0:Baam 0 · `694daecab79407da8550252c` |
| HotH: Abyss Weekend 7 | Cazual vs soullesswriter: Cazual 0:soullesswriter 2 · `694dadd0b79407da854f37a4` |
| HotH: Abyss Weekend 7 | Jericho vs vell1ar: vell1ar 2:Jericho 0 · `694dae6bb79407da854f9719` |
| HotH: Abyss Weekend 7 | Northwar vs herumple: Northwar 2:herumple 0 · `694f28fdb79407da85827ab4` |
| HotH: Abyss Weekend 7 | Northwar vs touchme: touchme 2:Northwar 0 · `69512bb4b79407da85bee32f` |
| HotH: Abyss Weekend 7 | Rer vs soullesswriter: Rer 2:soullesswriter 0 · `694ed654b79407da85701a92` |
| HotH: Abyss Weekend 7 | Rer vs tihedge: Rer 1:tihedge 1 · `695100e7b79407da85b71e98` |
| HotH: Abyss Weekend 7 | Rer vs vell1ar: vell1ar 0:Rer 2 · `69512b72b79407da85becfae` |
| HotH: Abyss Weekend 7 | kisselka vs tihedge: kisselka 0:tihedge 0 · `694e83bfb79407da855f1f2e` |

</details>

### Сетка на Challonge не завершена (15)

Abyss Cup Summer Playoff (состояние «underway»), Abyss New Gen Groups (состояние «group_stages_finalized»), New Gen 5 Groups (состояние «group_stages_finalized»), Summer Quals 2nd Stage Group A & B (состояние «group_stages_underway»), Summer Quals 2nd Stage Group C & D (состояние «group_stages_underway»), Summer Quals 2nd Stage Group E & F (состояние «group_stages_underway»), Summer Quals 2nd Stage Group G & H (состояние «group_stages_underway»), Summer Quals Group A & B (состояние «group_stages_underway»), Summer Quals Group C & D (состояние «group_stages_underway»), Summer Quals Group E & F (состояние «group_stages_underway»), Summer Quals Group G & H (состояние «group_stages_underway»), Summer Quals Group I & J (состояние «group_stages_underway»), Summer Quals Group K & L (состояние «group_stages_underway»), Summer Quals Group M & N (состояние «group_stages_underway»), Summer Quals Group O & P (состояние «group_stages_underway»)

Это сетки квалификаций и групп, где на Challonge не начат финальный этап. Групповые результаты учитываются.

## 5. Что уже привязано автоматически

Явные совпадения (регистр, leet, суффиксы). Отменить: `set-challonge-name "<имя>" --clear`.

antares/Antares → antares377 · AnTuR/Antur → X_AnTuR_X · Dead Inside/dead inside → deadinsidex (besforu) · divan2650 → divan · herumple7s → herumple · kureiton → kurei · Mina/mina → mina_rdm · Odin → odinzada · Oliverto → oliverto500 · RaftaliaLove/Raftlialover → raftalia · Rpyt → rpyt02 · Smertik/smertik/Smert → smertikk · Snusya/snusya → snusya.228 · Trunkscalibur FR/TrunkscaliburFR → Trunkscalibur · Velliar → vell1ar · Wanarin → wanar1n · wertmym` → wertmym21 · naomi_36 → Naomi · Kakarik → kakarikx · evenant.mrrr → revenant.mrrr · Fuclrum → Fulcrum · rerdi → Rer
