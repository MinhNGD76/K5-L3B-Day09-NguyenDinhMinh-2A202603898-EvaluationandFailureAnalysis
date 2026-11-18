# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (judge replay, FAIL là lớp dương). Số liệu dưới đây là output thật của lệnh đó; các hàm nằm ở `src/lab9/stats.py`, test `tests/test_lab9_stats.py` (confusion, P/R, κ, Rogan-Gladen) xanh.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Có (cả ba) | **dùng** |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không: κ và recall trượt | **loại** |

Ma trận nhầm lẫn (tp/fp/fn/tn): tone `24/4/6/66`; helpful `9/0/21/70`.
Rogan-Gladen: tone quan sát 0.28 → hiệu chỉnh 0.30; helpful quan sát 0.09 → hiệu chỉnh **0.30**. Judge helpful báo lỗi 9% trong khi tỉ lệ lỗi thật khoảng 30%.

## Audit thủ công (tone_ok, 10 bất đồng, nêu 8 case)
Cột "Ai đúng" theo ghi chú người gán nhãn trong CSV và đối chiếu lại với reply.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Xưng "em"/"nha" quá suồng sã. Rubric: cấm đại từ suồng sã ("em", "bạn" với khách), thêm 2 ví dụ FAIL. |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ thấy "Dạ, vui lòng"; câu cuối ra lệnh. Rubric: chấm cả câu, không chỉ phần mở đầu; giọng ra lệnh là FAIL. |
| 3 | H-042 "…đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý; judge phạt vì thiếu xin lỗi. Rubric: lời xin lỗi chỉ bắt buộc khi hệ thống lỗi hoặc giao trễ do LogiX, không bắt buộc ở mọi reply. |
| 4 | H-051 "…đã refund 90.000đ…" | FAIL | PASS | Người | "refund" được CS LogiX cho phép. Rubric: thêm danh sách từ vay mượn chấp nhận được. |
| 5 | H-081 "…chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket). Hành động: sửa nhãn thành FAIL ở bản nhãn người; không sửa rubric. Nếu sửa nhãn này thì tp=25, fp=3, P≈0.893 (không đổi kết luận). |
| 6 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ…" | FAIL | PASS | Người | Lặp "Dạ" là lỗi gõ, không ảnh hưởng giọng điệu. Rubric: lỗi gõ nhỏ không phải lỗi tone; để cho grader chính tả riêng nếu cần. |
| 7 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | Người, nhưng sai tiêu chí | Đây là hứa ngoài kết quả hệ thống (độ chính xác), không phải tone. Rubric: tách khỏi tone_ok; để cho grader FM-08/"promise" bằng code hoặc judge riêng. |
| 8 | H-094 "Da, LogiX da hoan 40.000đ… don O-341…" | PASS | FAIL | Người | Tiếng Việt mất dấu do dịch máy. Rubric: thêm điều kiện "viết tiếng Việt có dấu đầy đủ". |

Kiểu sai của judge tone: 6 lần cho PASS với reply suồng sã/ra lệnh/mất dấu (nhiễu ở phần "nhìn mở đầu"), 4 lần quá khắt khe (thiếu xin lỗi, từ "refund", lỗi gõ, nhãn sai). Hai lỗi đầu quan trọng hơn vì làm lọt reply xấu (R=0.8 vẫn đạt sàn).

## Kết luận
- **Dùng judge tone_ok làm tiêu chí gate**: κ=0.757, P=0.857, R=0.8 đều qua sàn. Dùng kèm số hiệu chỉnh Rogan-Gladen (0.30) khi báo tỉ lệ lỗi, không báo số thô (0.28).
- **Loại judge helpful, không dùng làm gate**: recall chỉ 0.3 (bắt 9/30 lỗi thật, bỏ sót 21), κ=0.375 < 0.6. Precision = 1.0 chỉ nghĩa là hễ nó báo FAIL thì đúng, nhưng nó gần như không bao giờ báo. Cả 21 bất đồng đều là judge cho PASS trong khi người gán FAIL: 18 case "sai tiền" (reply nêu số khác ledger, ví dụ HL-015 nói 55.000đ, ledger ghi 40.000đ) và 3 case "sai xưng hô" (HL-047, HL-091, HL-097 "Ok bạn…"). Judge bị hấp dẫn bởi lời xin lỗi dài dòng và văn phong lịch sự, không kiểm số tiền. Gate dựa trên nó sẽ cho qua gần hết lỗi FM-08.
- **Hành động**: không cần judge cho số tiền; tiền luôn chấm bằng code (metric FM-08 ở M3, so số trong reply với ledger). Chỉ dùng judge cho tone.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 mẫu mỗi tiêu chí, không có held-out thật); cần nhãn người mới để có held-out. Nhãn người không hoàn hảo (H-081), nên κ cũng phản ánh nhiễu nhãn.
