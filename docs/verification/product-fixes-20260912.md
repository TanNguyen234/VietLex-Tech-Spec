# Sửa runtime, UX và nghiệm thu thực tế — 12/09/2026

## Bản giao

- Runtime: `494f05d` — document-scoped retrieval không phụ thuộc PyVi ngoài production lock; structured generation có ngân sách output và trạng thái truncation; review không tự xác nhận luật hiện hành; query giữ số hiệu và tên luật.
- UX: `a1d3986` — giải thích chỉ số bằng tiếng Việt tại admin, usage/quality và Evaluation Lab, làm rõ đánh giá AI trong chat.
- Hai commit đã push origin/main. Vercel READY và promote: `dpl_DsfEQm4rwkgSaP4tNM8iMkovXttJ`, domain https://vietlex-legal-rag.vercel.app.
- GitHub Actions của `a1d3986`: [completed/success](https://github.com/TanNguyen234/VietLex-Tech-Spec/actions/runs/34694501218).
- Không đổi embedding/index, không reingest, không sửa credentials hoặc quota production. Workspace vẫn có thay đổi ngoài phạm vi từ trước; không đưa chúng vào hai commit trên.

## Bằng chứng trước và sau

| Nhánh | Trước, af8c9f5 | Sau, a1d3986 production |
| --- | --- | --- |
| Hỏi khoản 2 Điều 25 văn bản 333670 | 500 hai lần | 200; trả 60 ngày, dẫn đúng Điều 25 Khoản 2 và giới hạn hiệu lực |
| Phân tích nguồn đã chọn | 502 invalid_structured_response | 200, status ok, Vertex Gemini 3.5 Flash success |
| Bảng nghĩa vụ | 502 invalid_structured_response | 200, status ok, cùng provider thật |
| So sánh nguồn | 502 invalid_structured_response | Lần đầu 429 rate limit, retry 200 status ok |
| Điều 9999 không tồn tại | Chưa có nghiệm thu live | 429 rate limit rồi demo_daily_quota; NOT VERIFIED trên production |
| Hướng dẫn chỉ số | Thiếu giải thích | Evaluation Lab HTTP 200 có hướng dẫn mới; template tests pass |

Lượt sau deploy ghi 9 request: home, scope, selected, obligations, compare, missing_article, metric_guide, compare_retry, missing_article_retry. 429 được giữ như thất bại thực thi, không tính pass và không tắt giới hạn để làm đẹp báo cáo. Cookie và nội dung quản trị giữ trong thư mục tmp bị gitignore. Báo cáo không công bố credentials.

Diagnostic service với API thật trước deploy: structured response cũ có finish_reason MAX_TOKENS (439 output, 1081 thought tokens), JSON bị cắt; sau sửa STOP và JSON hoàn chỉnh (502 output). Review thật sau sửa nhận biết trích đoạn luật và yêu cầu kiểm tra hiệu lực. **Review production sau sửa chưa chạy lại**, không dùng kết quả service để giả thành nghiệm thu endpoint.

## Kiểm thử tự động

Lượt full đầu: 1261 pass, 2 fail. Một lỗi Git safe.directory của môi trường; một lỗi ResearchPlan Literal chưa chấp nhận version v2. Đã sửa và chạy lại hai case pass, sau đó chạy full suite mới:

```powershell
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest tests --ignore=tests/integration --ignore=tests/visual -q -p no:cacheprovider --basetemp=.tmp-product-fix-final-20260912 --junitxml=tmp/live-api-af8c9f5/fix-suite-final.xml
```

**1263 passed, 30 warnings, 490.33 giây.** Đây là unit/route/provider-free tests, có doubles trong tests; không phải 1263 lần gọi API thật. Integration và visual suite: NOT RUN trong lệnh này. Test TDD đã quan sát lỗi thiếu PyVi, truncation và prompt trước khi sửa.

```powershell
.venv/Scripts/python.exe -m ruff check app/services/deep_research.py app/services/document_scope.py app/services/research_analysis.py app/services/retrieval.py tests/services/test_deep_research.py tests/services/test_document_scope.py tests/services/test_research_analysis.py tests/test_public_templates.py
node --check app/static/js/vietlex.js
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
```

Cả ba kiểm tra pass trước hai commit đầu. Sau khi chụp UI phát hiện thêm lỗi artifact, source/config được sửa tiếp; vì vậy kết quả 1263 test chỉ áp dụng hai commit đầu, không tự chứng minh bản sửa packaging.

## Lỗi phát hiện khi chụp ảnh thật

Evaluation Lab trên a1d3986 trả 200 nhưng hiển thị `artifact unavailable`. Danh sách file từ API Vercel xác nhận không có `manifest.json` và `answer_results.json` trong upload. Chạy chính engine `ignore@4.0.6` đi kèm Vercel CLI 59.14.0 cho thấy directory `docs/evaluation` bị loại trước khi CLI đi tới exception của file.

Commit `93ec75d` bỏ trailing slash ở ba exception thư mục để walker đi vào được; giữ nguyên giới hạn chỉ hai artifact canonical. Đồng thời đường dẫn đọc được neo vào APP_ROOT, không phụ thuộc working directory. Test đổi cwd đã RED trước sửa. Focused route/deployment/service: 27 pass; sau sửa ignore, focused bundle/route: 5 pass.

**Full suite cuối: 1264 passed, 30 warnings, 462.87 giây** trên source/config 93ec75d. Lệnh giống ở trên, đổi `--basetemp=.tmp-product-package-final` và `--junitxml=tmp/live-api-af8c9f5/package-suite-final.xml`. Lượt trung gian bị ngắt khi phát hiện sửa thêm ignore không được dùng làm bằng chứng pass. Không sửa source/config sau lượt cuối này.

Deployment sửa cuối: `dpl_9CHPH6vTQAWpJXz1AzthFu4wQMP7`, READY và promote thành công. Kiểm tra public Evaluation Lab: HTTP 200, 78.478 byte, có `answer-v3-golden50-expanded14962`, không còn thông báo chưa khả dụng. Screenshot được chụp lại từ deployment này bằng Chrome thật, mở phần giải thích bằng thao tác click thông thường; không sửa DOM hoặc intercept network.

Admin overview và `/admin/usage` được kiểm tra bằng phiên thật sau deploy: HTTP 200, cả hai có hướng dẫn chỉ số. Đây là hai request bổ sung ngoài 9 request nghiệm thu runtime trên a1d3986. GitHub Actions của `93ec75d`: [completed/success](https://github.com/TanNguyen234/VietLex-Tech-Spec/actions/runs/34695489828).

Đây là minh chứng vì sao kiểm tra status HTTP và đọc chuỗi cấu hình chưa đủ: phải xem nội dung trang và kiểm tra artifact thực sự được đóng gói. Quy tắc đóng gói Python đối chiếu [tài liệu Vercel](https://vercel.com/docs/functions/runtimes/python), nhưng chẩn đoán cụ thể dựa trên file listing và engine CLI thực tế.

Lệnh live: `.venv/Scripts/python.exe -X utf8 tmp/live-api-af8c9f5/postfix.py`, sau đó retry bằng client thật cùng session. Các script/cookie ở tmp không phải test fixture phát hành.

## Phạm vi chưa đạt

- [Online 10 chủ đề](online-discovery-20260912/REPORT.md): 5/10 discovery; 0/5 câu tự nhiên. Không có cơ sở chứng nhận câu trả lời đúng/đủ từ metadata/snippet.
- Global retrieval câu thử việc đã bỏ lỡ Điều 25 trong baseline; không thay ranker hoặc index trong bản sửa này. Scoped Q&A thành công không chứng minh global retrieval đã được sửa.
- Logfire export 401 quan sát trong log Vercel; chưa sửa credential. Không coi là nguyên nhân đã chứng minh của scoped 500.
- Hiệu lực pháp lý, amendment history đầy đủ, toàn bộ corpus/article coverage chưa được chứng nhận.
- Model comparison, legal-effect promotion, PDF print, DOCX upload và mọi nhánh quyền/lỗi chưa được nghiệm thu toàn diện. Không tạo promotion hiệu lực giả.
- Chi phí API tổng cộng chưa xác định. Số HTTP request không tương đương số provider calls hoặc token bill.

## Files thay đổi

Runtime: `app/services/{deep_research,document_scope,research_analysis,retrieval}.py`; tests tương ứng trong `tests/services/`. UX: `app/static/js/vietlex.js`, `app/templates/{admin,admin_quality,evaluation_lab,metric_guide}.html`, `tests/test_public_templates.py`. Tài liệu: README, FEATURE_STATUS, PROJECT_CONTEXT, CURRENT_ARCHITECTURE, phân tích workflow, report và JSON online discovery. Ảnh UI chụp trang chạy thật được ghi riêng trong README.

Các kết quả này chứng minh một số lỗi kỹ thuật đã sửa, **không chứng minh sản phẩm production-ready hoặc đáp ứng đầy đủ report ban đầu**.
