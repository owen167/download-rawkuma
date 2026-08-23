# Manga Download Discord Bot

بوت Discord لتنزيل فصول المانجا من مصدرَي **Rawkuma** و**Naver Webtoon**. يستقبل روابط الأعمال أو الفصول عبر Slash Commands، يعرض معلومات العمل والغلاف وقائمة الفصول، ويضع عمليات التنزيل في Queue مع تحديث تقدّم داخل Embed واحد.

> لا يتجاوز المشروع DRM أو CAPTCHA أو Paywall أو أي حماية وصول. استخدمه فقط مع المحتوى الذي يسمح لك المصدر وحقوقه بتنزيله.

## أوامر Discord المدعومة

يحتوي البوت على **أمرين فقط**، ولا يسجل أوامر التنزيل القديمة:

```text
/download url:<Rawkuma URL>
/download-naver url:<Naver Webtoon URL>
```

يقبل كل أمر رابط عمل أو رابط فصل مباشر من مصدره. عند استخدام رابط العمل، يجلب البوت المعلومات والغلاف وعدد الفصول، ثم يعرض Embed وقائمة Select Menu متعددة الاختيار. كل صفحة تعرض 20 فصلًا، وتظهر زرا **Newer Chapters** و**Older Chapters** عند الحاجة. يمكن اختيار فصل واحد أو حتى 20 فصلًا من الصفحة نفسها، ثم يضيفها البوت إلى Queue وينزلها بالتسلسل، فصلًا واحدًا في كل مرة.

بعد اختيار الفصول، ينشئ البوت Job للفصل الحالي ويحدّث Embed التقدم أثناء تنزيل الصور. عند اكتمال الفصل، يرفعه إلى GoFile، يرسل Embed نهائيًا يحتوي رابط الفصل، يحذف Embed التقدم والملفات المحلية، ثم يبدأ الفصل التالي. لا توجد أوامر `/chapters` أو `/chapter` أو `/range` أو `/queue` أو `/cancel` أو أوامر Admin في هذا الإصدار.

## ما تم استخراجه من المصدر

تمت مراجعة مستودع `elboletaire/manga-downloader` عند الإصدار `v1.7.0` لإعادة تنفيذ حدود Rawkuma، كما تمت مراجعة مستودع `ZilverSick/comic.naver-downloader` عند الالتزام `766a528` لإضافة حدود Naver العامة. يعتمد Naver على صفحة القائمة `webtoon/list?titleId=...` وصفحة الحلقة `webtoon/detail?titleId=...&no=...` ووسوم صور العارض. تم تنفيذ `NaverDownloader` مستقلًا، ولم يتم نسخ CLI أو مدير البيئة أو التنزيل المتوازي من المشروع المرجعي. تفاصيل النسب والتراخيص موجودة في `docs/source-review.md` و`THIRD_PARTY_NOTICES.md`.

## البنية

```text
.
├── main.py
├── requirements.txt
├── src/rawkuma_bot/
│   ├── commands/discord_bot.py
│   ├── config/settings.py
│   ├── database/schema.py
│   ├── downloaders/models.py
│   ├── downloaders/rawkuma/downloader.py
│   ├── downloaders/naver/downloader.py
│   ├── services/archive.py
│   ├── services/manager.py
│   └── storage/base.py
├── tests/
├── data/
├── temp/
├── downloads/
├── THIRD_PARTY_AGPL-3.0.txt
├── THIRD_PARTY_MIT_COMIC_NAVER_DOWNLOADER.txt
└── THIRD_PARTY_NOTICES.md
```

## التثبيت والتشغيل

يتطلب Python 3.11 أو أحدث. أنشئ بيئة افتراضية وثبّت المتطلبات:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

ضع `DISCORD_TOKEN` في `.env` فقط. يفضل وضع `DISCORD_GUILD_ID` أثناء الاختبار حتى يظهر الأمر بسرعة داخل سيرفر واحد. لا ترفع `.env` أو Cookies أو أي Credentials إلى Git.

## Logging

يكتب البوت سجلًا مستمرًا في `logs/rawkuma-bot.log`، وسجلًا منفصلًا للأخطاء في `logs/errors.log`. الملفات تستخدم تدويرًا تلقائيًا بحد أقصى 5 MB لكل ملف مع الاحتفاظ بخمس نسخ احتياطية. يسجل البوت بدء التشغيل، جاهزية قاعدة البيانات، اتصال Discord، مراحل كل Job، أخطاء الشبكة والتنزيل، وأخطاء Discord. يوجد مرشح Redaction يخفي القيم التي تشبه Tokens أو Cookies أو مفاتيح API. عند حدوث مشكلة، أرسل محتوى `logs/errors.log` أو آخر أسطر من `logs/rawkuma-bot.log` بعد حذف أي بيانات سرية.

## التخزين والتنظيف

ينشئ كل Job مجلدًا مستقلًا تحت `temp/job_<id>/chapter_<number>/`. تُنزّل الصور مباشرة إلى الملفات بدل تجميعها كلها في الذاكرة، وتُحافظ على امتداد الصورة الأصلي عندما يكون معروفًا. يجمع البوت صور كل فصل في ملف `Chapter_<number>.zip` مع الحفاظ على ترتيب الصفحات وامتداداتها، ثم يرفع ملف ZIP نفسه إلى GoFile ويرسل رابط صفحة التحميل في Embed نهائي باللغة الإنجليزية. بعد إرسال الرابط، يحذف البوت Embed التقدم وسجل الوظيفة ومجلد الصور وملف ZIP المحلي مباشرة، مع بقاء النسخة المنشورة لدى GoFile. يتطلب استخدام حساب GoFile ثابتًا وضع `GOFILE_TOKEN` في `.env`؛ وإذا تُرك فارغًا يستخدم GoFile حسابًا ضيفًا عند الرفع. توجد واجهة `StorageAdapter` لإضافة مزود تخزين آخر لاحقًا.

## الإعدادات

| المتغير | الافتراضي | الوظيفة |
|---|---:|---|
| `DISCORD_TOKEN` | مطلوب | توكن البوت |
| `DISCORD_GUILD_ID` | فارغ | مزامنة أوامر أسرع داخل Guild |
| `GOFILE_TOKEN` | فارغ | توكن حساب GoFile؛ إذا كان فارغًا يستخدم حساب GoFile ضيفًا |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | محفوظ للتوافق؛ تنزيل الفصول يظل تسلسليًا بعامل واحد |
| `MAX_CONCURRENT_PAGES` | `6` | عدد صور الفصل المتزامنة داخل الفصل الحالي |
| `MAX_CHAPTERS_PER_JOB` | `20` | الحد الأقصى للفصول المختارة من القائمة |
| `RETRY_ATTEMPTS` | `3` | محاولات الصور ورفع GoFile الفاشلة |
| `DISCORD_MAX_FILE_MB` | `25` | إعداد قديم محفوظ للتوافق؛ لا يُرسل ZIP إلى Discord في وضع GoFile |
| `DATABASE_URL` | SQLite | مكان قاعدة البيانات |
| `LOG_DIR` | `./logs` | مجلد ملفات اللوج |

## الترخيص

هذا المشروع يعيد تنفيذ حدود Rawkuma وNaver العامة اعتمادًا على دراسة سلوك المشروعين المرجعيين. توجد إشعارات المصدر والتراخيص في `THIRD_PARTY_AGPL-3.0.txt` و`THIRD_PARTY_NOTICES.md`. راجع التزامات AGPL-3.0 وMIT وشروط المصدر قبل نشر نسخة معدلة كخدمة شبكة.

## الاختبارات

```bash
pytest -q
python3 -m compileall -q main.py src
```

الاختبارات تستخدم HTML محليًا وMocks ولا تعتمد على تحميل محتوى حي. اختبر التنزيل الحقيقي فقط على محتوى لديك حق استخدامه.
