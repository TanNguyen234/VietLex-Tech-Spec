# VietLex — chấm rubric trực tiếp 2026-11-15 (nhật ký từng câu)

Môi trường: APP_ENV=test, 127.0.0.1:8101, retrieval vertex-qdrant-v3, MongoDB Atlas (Legal-RAG) sẵn sàng. Trình duyệt Playwright headed. Mỗi câu hỏi mở hội thoại mới ("+ Mới") trừ câu nối tiếp.
Rubric (6 tiêu chí): (1) hiểu tình huống/hỏi lại; (2) căn cứ đúng và còn hiệu lực, số điều/khoản có thật; (3) kết luận hợp lý, nêu điều kiện/ngoại lệ; (4) hướng dẫn hành động cụ thể; (5) đầy đủ, không lan man, tiếng Việt tự nhiên, có lưu ý; (6) không bịa văn bản/điều/số liệu. Một tiêu chí FAIL → câu FAIL.

| # | Câu hỏi | Kết quả | Lý do chính (tiêu chí) |
|---|---|---|---|
| Q01 | sếp quịt tiền trợ cấp thực tập | FAIL | (2) căn cứ Nghị định 102-TTg năm 1962 (Điều 8) là nguồn duy nhất; app tự nhận không xác nhận hiệu lực; (3) kết luận "không bị coi là vi phạm pháp luật" quá khẳng định; (4) thiếu hướng dẫn chứng cứ, thời hiệu, cơ quan. |
| Q02 | công ty bắt ký thử việc 3 tháng lương 70% | FAIL (cần xác minh) | Nội dung đúng hướng: lương thử việc ≥85% (BLLĐ 2019 Điều 26), thời hạn thử việc theo nhóm (Điều 25). Trừ điểm: (4) thiếu hành động cụ thể (yêu cầu điều chỉnh, khiếu nại, thanh tra lao động, giữ hợp đồng); (5) trình bày dài. Cần đối chiếu Điều 24–26 trong corpus. |
| Q03 | nghỉ việc ngang thì có bị giữ lương tháng cuối không | FAIL | (2) căn cứ sai: Điều 115 BLLĐ 2019 là nghỉ việc riêng, không liên quan nghỉ ngang; không dẫn các điều về đơn phương chấm dứt HĐLĐ và thanh toán lương; (3) không kết luận; (4) không hướng dẫn. |
| Q04 | chồng ngoại tình, ly hôn, giành nuôi con 2 tuổi | FAIL | (2) dựa Nghị quyết 02/2000/NQ-HĐTP (cần kiểm tra còn hiệu lực); không dẫn Luật Hôn nhân và Gia đình 2014 (52/2014/QH13); (3) bỏ trống câu hỏi chính về nuôi con (cần Điều 81 — con dưới 36 tháng tuổi). |
| Q05 | mua đất giấy tay 2010, làm sổ đỏ được không | FAIL | (2) áp dụng sai quy định chuyển tiếp của Luật Đất đai 2003 (Điều 50 khoản 7 dành cho đất từ 15/10/1993 đến trước 2004) cho giao dịch năm 2010; dẫn Luật Cải cách ruộng đất 1953 và 197/SL không liên quan; không xét Luật Đất đai hiện hành. |
| Q06 | phạt nồng độ cồn xe máy mức thấp nhất | FAIL | (2)(3) không trả lời; dẫn VBHN 19/2014, NĐ 152/2005, QĐ 60/2005 không đúng nội dung; không dẫn văn bản xử phạt hiện hành về nồng độ cồn. |
| Q07 | cho vay 50 triệu không giấy tờ, kiện được không | FAIL | (2) căn cứ là Hướng dẫn 8055/NHCS-TDSV và 7886/NHCS-TDNN (nghiệp vụ ngân hàng chính sách), không áp dụng cho cho vay dân sự; không dẫn BLDS 2015 (chứng cứ, thời hiệu). |
| Q08 | ngoài phạm vi (món ăn) | PASS | từ chối đúng: "Hệ thống chỉ hỗ trợ giải đáp ... pháp luật Việt Nam". |
| Q09 | luật này còn hiệu lực không (mơ hồ) | FAIL | (1) không hỏi lại "luật nào"; (5) trả trích đoạn Luật Ban hành VBQPPL 1996 và nguồn nhãn "Khongso" không liên quan. |
| Q10 | Điều 999 BLLĐ 2019 (bẫy) | PASS | (6) không bịa điều luật; nêu không đủ dữ liệu. Thiếu: nói rõ BLLĐ 2019 không có Điều 999 và gợi ý Điều 26 (lương thử việc). |
| Q11 | thừa kế, con riêng ngoài giá thú | FAIL | (2) căn cứ Nghị quyết 02/HĐTP (cũ; app tự nhận chưa xác minh hiệu lực); không dẫn BLDS 2015 (thừa kế theo pháp luật). |
| Q12 | lương tối thiểu vùng 2026 | FAIL | (2)(4) không nêu văn bản quy định mức hiện hành và nơi tra cứu; chỉ trích BLLĐ 2019 Điều 91 phần định nghĩa. |
| Q13 | nghỉ thai sản và BHXH | FAIL | guard trả "Kiểm tra tự động phát hiện câu trả lời chưa được tài liệu hỗ trợ đầy đủ", không có nội dung; nguồn không liên quan (TT 03/2007, văn bản hưu trí 2026). |
| Q14 | freelance 20 triệu, thuế TNCN | FAIL | (2) nguồn không liên quan (VBHN 112, 04/VBHN-BTC); (3) không kết luận; (4) thiếu MST, mức thuế, kê khai. |
| Q15 | đổi người đại diện pháp luật | FAIL | (2) LDN 2020 Điều 12 đúng hướng nhưng dẫn TTLT 05/1998 đã cũ; (4) thiếu thủ tục đăng ký thay đổi, hồ sơ, thời hạn. |
| Q16 | mua online giao sai, shop không hoàn tiền | FAIL | (2) LCL hàng hóa 2007 và NĐ 91-HĐBT (1990) đã cũ; (4) thiếu kênh khiếu nại hiện hành. |
| Q17 | không đội mũ bảo hiểm phạt bao nhiêu | FAIL | (3)(4) không nêu mức phạt; dẫn NQ 13/2002 và VBHN 19/2014 đã cũ. |
| Q18 | trộm điện thoại 2 triệu, có đi tù không | FAIL | (2) dẫn Pháp lệnh 1970 và TTLT 02/2001 theo BLHS 1999; kết luận sai (cho rằng 650–750 nghìn có thể truy cứu hình sự). Thiếu BLHS hiện hành. |
| Q19 | làm lại CCCD | FAIL | (2) dẫn Luật CCCD 2014 (59/2014/QH13), cần xác minh còn hiệu lực (Luật CCCD 2023); lệ phí không có nguồn hiện hành. |
| Q20 | kết hôn với người nước ngoài | FAIL | guard fallback; nguồn không liên quan (12-HĐBT 1990, 503-LB/TT). |
| Q21 | sổ đỏ mất làm lại | FAIL | (2) dẫn NĐ 95/2005 (cần xác minh còn hiệu lực, đã có văn bản thay thế); nguồn 108/NHCSXH-KHNV, 9645/HD-ĐB không liên quan. |
| Q22 | sa thải trái pháp luật, bồi thường | FAIL | (2)(6) dẫn NĐ 165/HĐBT (1988), mức "3 tháng tiền công" không đối chiếu được với BLLĐ hiện hành; thiếu BLLĐ 2019 (Điều 41–42, cần xác minh). |
| Q23 | báo trước khi nghỉ việc HĐKXĐTH | FAIL | nội dung (45 ngày; 3 ngày khi ốm) đúng hướng nhưng căn cứ BLLĐ sửa đổi 2002 (35/2002/QH10) đã hết hiệu lực; cần BLLĐ 2019 Điều 35. |
| Q24 | công ty không đóng BHXH | FAIL | trọng tâm lệch (ngày nghỉ không đóng); căn cứ 50/VBHN-VPQH (Luật BHXH 2014, cần xác minh thay thế); thiếu khiếu nại BHXH, thanh tra. |
| Q25 | bán online nhỏ lẻ, có đăng ký hộ kinh doanh không | FAIL | nguồn lệch phạm vi (CV 1840 TCT/DNK, VBHN 26 Điều 31 về sang băng đĩa); không trả lời điều kiện. |
| Q26 | xe máy mới lỗi tuần đầu, đổi trả | FAIL | (2) dẫn LCL hàng hóa 2007 Điều 17 khoản 3 (cần xác minh); (4) thiếu thời hạn và thủ tục hiện hành. |
| Q27 | đặt cọc thuê nhà, không trả cọc | FAIL | (2) BLDS 2015 Điều 328 khoản 2 đúng hướng; (4) thiếu bước cụ thể (hòa giải, đòi, khởi kiện, thời hiệu). |
| Q30 | nối tiếp: nghỉ ngang không báo trước | FAIL | (1) giữ được ngữ cảnh; (2) căn cứ CV 2948/LĐTBXH-LĐVL và "Điều 41" khoản 2–4 không nêu mức bồi thường; chưa dẫn BLLĐ 2019 hiện hành. |
| Q28, Q29, Q31 | lãi suất vay tối đa; Điều 812 BLDS 2015 (bẫy); xin trốn thuế | chưa chạy | cần chạy tiếp sau khi xong yêu cầu UI/tính năng. |

Tổng: 30 câu đã chạy; PASS 2 (Q08, Q10); FAIL 28. Gate VietLex chưa đạt.
