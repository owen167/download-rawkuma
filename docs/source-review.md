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
