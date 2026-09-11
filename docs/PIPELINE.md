# Pipeline / Quality Gates

لا تنتقل أي مرحلة إلى الحالة التالية إلا بعد اجتياز بوابة الجودة الخاصة بها.

## المراحل
1. Repository integrity — التحقق من بنية المستودع وعدم وجود أسرار.
2. Application bootstrap — تشغيل التطبيق محلياً بنجاح.
3. Static checks — lint/type/config checks.
4. Unit tests — اختبارات الوحدات.
5. Integration tests — اختبارات التكامل.
6. Security checks — المصادقة والجلسات والصلاحيات وإخفاء الأسرار.
7. Build — بناء الواجهة/الخدمات بنجاح.
8. Deployment smoke test — اختبار تشغيل البيئة المنشورة.
9. Production readiness — مراجعة أخيرة قبل تفعيل النشر التلقائي.

## قاعدة مهمة
الفشل في أي Gate = 🔴 STOP. يتم إصلاح السبب وإعادة الاختبار قبل المتابعة.

## حالات لوحة المتابعة
- 🟢 PASS
- 🟡 RUNNING
- 🔴 FAILED
- ⚪ NOT RUN

لا نعتبر المشروع Production-Ready بناءً على وجود الملفات فقط؛ يجب أن تكون الاختبارات الفعلية ناجحة.
