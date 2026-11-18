# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case: C-002@11 trên `seeded_regression`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run `E-seeded_regression-20261118-df3d` (`src/reports/eval_seeded_regression.json`) |
| Triệu chứng | Lab 8 grader FAIL `status resolved != denied`. Ledger ghi `refund_vnd=20000`, `refund_count=1`; nhãn là `denied`, 0đ. Reply nói "LogiX đã hoàn 20.000đ cho đơn O-202" nên reply và ledger khớp nhau; chỉ quyết định là sai |
| Bước sai đầu tiên | Event 3 `model_override {"delay_days": 5}`: agent ghi đè số ngày trễ bằng số trong ticket |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng (tool cho phép, phạm vi principal). Event 2 `investigator` trả `lookup_order visible=true`, đơn O-202 `delivered` với `delay_days=2` trong DB (không đủ 4 ngày để được hoàn) còn ticket ghi 5 ngày. Event 4 `quote` 20.000đ, event 5 `refund_history`, event 6 `reply` chỉ là hệ quả của event 3 |
| Failure mode | FM-03 ticket_trust |
| Đối chứng | `fixed C-002@11`: không có `model_override`; event 3 `quote {"amount_vnd": 0, "reason": "no_entitlement"}`, reply "chưa đủ điều kiện", ledger 0đ, grader PASS |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_c002_ticket_override_is_first_wrong_step` (variant lỗi: `model_override` ở event 3, ledger 20.000đ) và `test_c002_fixed_keeps_db_fact` (`fixed`: không override, 0đ). Đã thấy fail-condition trên variant lỗi và pass trên `fixed`; cả hai xanh. Grader `DbFactKept` (mức bước) cũng bắt đúng event này |
| Chưa chắc chắn | Trace cho thấy override xảy ra nhưng không cho thấy MockLLM "vì sao" chọn số của ticket; lỗi này là công tắc gài sẵn `ticket_trust`, không chứng minh hành vi của model thật |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
