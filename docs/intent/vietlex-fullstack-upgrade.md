# Confirmed Statement of Intent — VietLex V4 Full-Stack Upgrade

**Date:** 2026-11-18  
**Branch:** `feat/vietlex-v4-fullstack-upgrade`  
**Status:** Confirmed by User (`Yes`) via `/interview-me`

## Statement of Intent

- **Outcome:** Đại tu toàn diện hệ thống VietLex từ trong ra ngoài trên nhánh mới (`feat/vietlex-v4-fullstack-upgrade`):
  1. Tái cấu trúc dữ liệu & chỉ mục Qdrant Cloud + Supabase ngay trong ngưỡng **Free-Tier** (thu hồi dung lượng chết, loại bỏ văn bản rác `1924–2009` và gỡ bỏ trần cắt `16 chunks/văn bản`, nạp trọn vẹn điều khoản các Bộ luật/Luật hiện hành + Nghị định/Nghị quyết TW `2015–2026` + Thông tư trọng yếu `2020–2026`).
  2. Tích hợp **Tavily (`Search` + `Extract`)** theo mô hình phân tầng độ tin cậy (Tier-1 cổng công quyền `.gov.vn`/`chinhphu.vn`/`congbao`/`vbpl.vn`/`quochoi.vn` + Tier-2 định vị ngữ nghĩa số hiệu/Điều khoản/tình trạng hiệu lực) để bù đắp phần đuôi dài và văn bản mới ban hành trong `2–5s`.
  3. Giải phóng tầng điều phối **AI Provider** (cho phép gọi thoải mái mọi provider đã tích hợp khi dev/fix/test và tài khoản Admin, sửa lỗi đứt gãy fallback/cooldown/JSON-mode, khôi phục Semantic Cache sau Input Guardrail, sửa lỗi nghẽn `active_bodies >= 2` của `ReviewerDemoMiddleware`).
  4. Nâng cấp trọn vẹn **UI/UX & Công cụ Nghiệp vụ Luật** trên nền FastAPI + Jinja SSR (SSE token streaming thật + nút Dừng, giao diện gọn sáng cho người dân nối mượt sang Workspace chuẩn luật sư: giữ đánh số tự động DOCX `<w:numPr>`, Redline từng từ chính xác, Full Contract Review tự động gộp bảng Findings, xuất báo cáo DOCX tiếng Việt chuẩn định dạng).
- **User:** Phục vụ đồng thời **người dùng phổ thông** (hỏi đáp tình huống pháp lý đời thường nhanh, dễ hiểu, có hướng dẫn hành động thực tế) và **người trong ngành luật** (luật sư, pháp chế, compliance cần tra cứu sâu, rà soát hợp đồng, đối chiếu Redline, kiểm chứng căn cứ và xuất báo cáo chuyên nghiệp).
- **Why now:** Kiểm toán pháp y tại `HEAD 431003a` chỉ ra hệ thống trượt `18/31` câu hỏi thực tế do `77.45%` kho online là văn bản cũ trước năm 2010 (`0` Nghị định/Thông tư `2019–2025`), cắt mất `88%–97.7%` số Điều của các Bộ luật, duyệt web cổng Chính phủ/VBPL chậm `50s+` và lỗi `403`, bẫy từ chối tự động sau truy xuất, cùng nhiều lỗi đầu-cuối ở công cụ DOCX/Redline/Workspace.
- **Success:**
  - `/chat` stream token thời gian thực (`TTFT < 3–5s`), có nút Hủy, không chồng chéo 5 lớp disclaimer, vượt qua bộ kiểm thử thực tế 31 câu hỏi đời thường + Golden benchmark mà không bịa số hiệu/điều khoản.
  - `/search`, `/documents/{id}` và toàn bộ 7 phân khu `/workspaces` hoạt động hoàn chỉnh đầu-cuối (upload DOCX giữ nguyên số Điều & bảng, Redline hiển thị thay đổi cấp độ từ, rà soát hợp đồng chạy theo lô tự động vào 1 bảng Findings, xuất file DOCX tiếng Việt có `styles.xml` chuẩn).
  - Toàn bộ provider-free test suite (`pytest -m "not live"` + Node JS tests) và live E2E verification đều xanh.
- **Constraint:**
  - Lưu trữ đám mây gói gọn trong **Free-Tier** của Qdrant Cloud (`4.00 GiB` disk / `1.00 GiB` RAM) và Supabase (`500 MB`).
  - Sử dụng `TAVILY_API` / `TAVILY_API_KEY` và các AI provider có sẵn trong `.env` tự do cho quá trình dev/re-index/test & Admin; **giữ nguyên hàng rào quota/rate-limit bảo vệ đối với người dùng thường/khách vãng lai trên môi trường public**.
  - Làm việc trực tiếp trên nhánh `feat/vietlex-v4-fullstack-upgrade` (không nhân bản `git worktree` gây đầy ổ đĩa).
- **Out of scope:**
  - Không viết lại kiến trúc sang SPA (React/Next.js) thay thế FastAPI + Jinja SSR.
  - Không nâng cấp lên gói trả phí của Qdrant Cloud, Supabase hay MongoDB Atlas.
  - Không gỡ bỏ cơ chế giới hạn quota ngày/phút đối với người dùng bên ngoài trên bản public/demo.
