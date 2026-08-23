# Source reviews

## Rawkuma source review

تمت مراجعة مستودع [elboletaire/manga-downloader](https://github.com/elboletaire/manga-downloader) عند الإصدار `v1.7.0` والالتزام الموجود في `1d7bef7`. المشروع الأصلي مرخص بموجب **AGPL-3.0**، ولذلك تم حفظ نص الترخيص في `THIRD_PARTY_AGPL-3.0.txt` وتوثيق الحدود في `THIRD_PARTY_NOTICES.md`.

## الحدود المستخرجة

يتم التعامل مع Rawkuma في المصدر الأصلي عبر `grabber/plainhtml.go` وليس عبر Downloader مخصص. اكتشاف الصفحة يعتمد على وجود صفوف `#chapter-list [data-chapter-number]`، ويُستخرج اسم العمل من `h1[itemprop="name"]`. يحتوي كل صف على رابط `a` ورقم الفصل في `data-chapter-number`، وتُحل الروابط النسبية بالنسبة إلى صفحة العمل. صفحات القراءة تستخدم `[data-image-data] img`، كما يدعم المصدر الأصلي المتغير `var chapImages = '...'` لاستخراج الصور المرتبة.

من `downloader/fetch.go` تم تحليل النمط العام المطلوب: حد توازي للصور، callback للتقدم، إعادة المحاولة عند فشل GET أو قراءة المحتوى، ثم ترتيب النتائج حسب رقم الصفحة. تمت إعادة كتابة هذا السلوك في `RawkumaDownloader` بلغة Python و`aiohttp`، مع حفظ الصور مباشرة إلى ملفات لتقليل استهلاك الذاكرة.

لم تتم إعادة استخدام CLI أو Cobra أو واجهة الطرفية أو محددات المواقع الأخرى أو packer العام. المشروع الحالي Rawkuma-only ويضع Downloader منفصلًا عن Discord Commands.

## قيود الاستخدام

لا يحاول المشروع تجاوز DRM أو CAPTCHA أو Paywall أو تسجيل الدخول. يجب استخدامه فقط مع صفحات ومحتوى يملك المستخدم حق تنزيله، كما يجب مراجعة التزامات AGPL-3.0 قبل توزيع نسخة معدلة أو تشغيلها كخدمة شبكة.

## Naver Webtoon source review

تمت مراجعة مستودع [ZilverSick/comic.naver-downloader](https://github.com/ZilverSick/comic.naver-downloader) عند الالتزام `766a528`. المشروع الأصلي مرخص بموجب **MIT**، وصاحب حقوقه المذكور في الترخيص هو `kikunayar` (2024). تم حفظ النسبة المطلوبة في `THIRD_PARTY_NOTICES.md`.

يعتمد منطق Naver المراجع على صفحة العمل `https://comic.naver.com/webtoon/list?titleId=...` لاستخراج `og:title`، وعلى صفحات الحلقات `https://comic.naver.com/webtoon/detail?titleId=...&no=...` لاستخراج صور القراءة من عناصر `img` داخل عارض الحلقة. إعادة التنفيذ الحالية تعزل هذا الحد العام في `NaverDownloader`، وتستبعد مدير البيئة الافتراضية وواجهة CLI والتنزيل المتوازي في المشروع المرجعي، لأن مدير البوت ينفذ الفصول بالتتابع ويستخدم callback للتقدم.

لا يعتمد التكامل على حساب أو ملفات تعريف ارتباط أو endpoint خاص، ولا يحاول تجاوز DRM أو CAPTCHA أو Paywall أو تسجيل الدخول. قد تختلف بنية HTML أو إتاحة الصور من Naver بمرور الوقت؛ عندها يسجل البوت الخطأ الآمن ويرسل Embed إنجليزيًا عامًا للمستخدم. يجب استخدام الأمر مع محتوى يسمح المستخدم بتنزيله وفق شروط المصدر والقانون المحلي.

## Kakao Webtoon source review

تمت مراجعة مستودع [ImSejin/kakao-webtoon-downloader](https://github.com/ImSejin/kakao-webtoon-downloader) عند الالتزام `0d4be7d`. المشروع الأصلي مرخص بموجب **MIT**، وحقوقه المذكورة في الترخيص تعود إلى `Im Sejin` (2021). تم حفظ نص MIT الكامل في `THIRD_PARTY_MIT_IMSEJIN_KAKAO_DOWNLOADER.txt` وإضافة إشعار النسبة إلى `THIRD_PARTY_NOTICES.md`.

المشروع المرجعي يستخدم رابط Kakao بصيغة `https://webtoon.kakao.com/content/<title>/<content_id>`. إعادة التنفيذ الحالية تستخدم جلسة Chromium مجهولة لفتح واجهات Kakao الطبيعية، وتستخرج بيانات العمل من واجهة profile، وقائمة الحلقات من واجهة `episode/v2`. تنزيل الصور يفتح رابط العارض الرسمي ويقرأ الصور التي يعرضها العارض نفسه كـ`blob:http` ثم يحفظها بعد التعرف على تنسيق البايتات. لا يتم تمرير Cookies خاصة أو رموز دخول إلى المتصفح.

قبل تنزيل أي حلقة، يتحقق `KakaoDownloader` من قيمة `readable` التي يعيدها Kakao. إذا كانت الحلقة غير مقروءة أو مدفوعة أو لم يعرضها Kakao للقارئ المجهول، يرفضها البوت برسالة Embed إنجليزية عامة. لا يحاول التكامل تجاوز DRM أو CAPTCHA أو Paywall أو تسجيل الدخول أو قيود العمر أو أي حماية وصول.

أثناء المراجعة الحية، أعادت واجهة بيانات المحتوى HTTP 200، وأعادت واجهة الحلقات الحديثة HTTP 200 داخل جلسة المتصفح المجهولة، بينما أعادت الواجهة القديمة HTTP 403 دون جلسة. لذلك تم اعتماد واجهة v2 داخل المتصفح الطبيعي فقط، مع إبقاء fallback الآمن هو إبلاغ المستخدم بأن المصدر غير متاح إذا تغيّر Kakao أو منع الجلسة المجهولة. يتطلب هذا المسار Playwright ومتصفح Chromium متاحًا في بيئة التشغيل.

لم يتم نسخ تطبيق Electron أو Cookies الثابتة أو كود المشروع المرجعي كاملًا. كما لم يتم تعديل مُنزّلي Rawkuma وNaver؛ Kakao موجود في حزمة `downloaders/kakao` مستقلة، ويرتبط بالأمر `/download-kakao` فقط.
