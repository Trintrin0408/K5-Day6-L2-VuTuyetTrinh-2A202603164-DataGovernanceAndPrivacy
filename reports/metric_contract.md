# Metric contract — T02 Raw QC Triage

> Contract này được chốt theo `docs/tracks/T02.md`, `configs/tracks/t02.yaml` và
> evaluator `src/metrics/tracks.py::eval_t02`. Pipeline không đọc ground truth;
> ground truth chỉ được evaluator của giảng viên dùng khi chấm.

| Mục | Khai báo của nhóm |
|---|---|
| Track | **T02 — Raw QC Triage** |
| Primary metric (tên đúng như evaluator in ra) | **Defect Recall@B** |
| Tăng tốt hay giảm tốt? | **Higher is better** |
| Đơn vị đánh giá | **Image** |
| Công thức + numerator / denominator | `Defect Recall@B = TP / P_eval`; `TP` = số ảnh có `is_defect=1` nằm trong top-B theo `score` giảm dần; `P_eval` = tổng số ảnh lỗi (`is_defect=1`) trong split eval. |
| Cách ghép prediction ↔ GT | Ghép bằng `image_id`; chỉ giữ prediction có `image_id` xuất hiện trong GT; xếp hạng theo `score` giảm dần bằng stable `mergesort`. Không dùng `path`, metadata hoặc thứ tự file để ghép. |
| Candidate pool cố định | `fixtures/t02_raw_qc/images.csv`: **96 ảnh**, gồm **56 dev** và **40 eval**; split theo cảnh gốc, không trộn dev/eval. |
| Review budget B / K | **B = 20 ảnh** cho top-20 review queue; config: `params.budget=20`, `eval_params.budget=20`. T02 không dùng K riêng. |
| Seed | **42** cho baseline/PoC và các phép bootstrap dự kiến. |
| Threshold policy (chọn trên dev như thế nào) | Không tune threshold trên eval. Các hằng số feature được chốt trước: blur `75`, dark mean `55`, glare `p95=220`, glare saturation `0.08`, dark fraction `0.50`, block boundary `8 px`; trọng số `blur/dark/glare/compression = 0.45/0.25/0.20/0.10`. `score >= 0.45` chỉ tạo `suggested_action=RECAPTURE`; metric Recall@B chỉ phụ thuộc thứ hạng, không phụ thuộc threshold này. |
| Eval split (không dùng để tune) | **`split=eval`**, N = **40 ảnh**; lấy từ `configs/tracks/t02.yaml` (`eval_params.split: eval`). |
| Chỉ số lỗi xấu | **Miss/FN**: ảnh lỗi ngoài top-20. **False alarm/FP**: ảnh sạch bị đưa vào top-20. **False reject** ở mức quyết định: ảnh sạch bị reviewer xác nhận `RECAPTURE`; cần tách khỏi false alarm tự động khi có review labels. |
| Slices sẽ báo cáo (≥2) | `light=day`, `light=dusk`, `light=night`; bổ sung `camera_id=cam_A/cam_B` và `defect_type` khi có GT. Với mỗi slice báo `recall_in_topB` và `false_alarm_in_topB`. |
| Metric phụ | **Precision@B** = `TP / B`, higher is better. **False alarm in top-B** theo slice = `clean images in top-B / clean images in slice`, lower is better. **Defect-type accuracy** chỉ báo khi prediction có cột `pred_defect_type`; output hiện tại chưa có cột này. |
| Cách báo độ bất định khi N nhỏ | Báo **Wilson 95% CI** cho Recall@B và Precision@B. Báo thêm bootstrap theo **10 cảnh eval**, 1.000 lần, seed 42 cho `Δ(PoC - baseline)`. Chỉ kết luận PoC tốt hơn khi CI của delta không chứa 0. Hiện chưa sinh được các CI này vì repo học viên không có `fixtures/t02_raw_qc/gt/labels.csv`. |
| Baseline comparison | So sánh với baseline trên cùng candidate pool, cùng split eval, cùng B=20 và seed 42. Baseline hiện có trong repo là random baseline; baseline Laplacian một ngưỡng như phần gợi ý của T02 chưa được cài. |
| Output prediction contract | `ranked_review.csv` bắt buộc có `image_id,score`; các cột hiện có thêm `reason`, `suggested_action`, `pred_action` và metadata/feature để audit. `score` cao hơn nghĩa là ưu tiên review cao hơn. |
| Human decision policy | Chưa review top-20 → `HOLD/REVIEW_REQUIRED`; có ít nhất một quyết định `RECAPTURE` → `REWORK/RECAPTURE_REQUIRED`; review xong và không có `RECAPTURE` → `GO/REVIEWED_KEEP`. |
| Ngày giờ chốt + người chốt | **2026-11-14 (ICT)** — Luong Hoang Bao Tran và Vu Tuyet Trinh; contract được đối chiếu lại sau khi pull commit `784f1bc`. |

## Quy tắc tính điểm của PoC

PoC tạo ranking score từ bốn tín hiệu ảnh, đều được chuẩn hóa về `[0, 1]`:

```text
score = 0.45 * blur_score
      + 0.25 * dark_score
      + 0.20 * glare_score
      + 0.10 * compression_score
```

`blur_score` dùng variance of Laplacian; `dark_score` dùng brightness mean và
tỷ lệ pixel tối; `glare_score` dùng p95 brightness và tỷ lệ pixel bão hòa;
`compression_score` là proxy blockiness tại biên block JPEG 8 pixel. Các tín
hiệu này chỉ dùng để xếp hạng và giải thích cho reviewer, không được xem là
ground-truth defect labels.

## Trạng thái đo lường hiện tại

Ground truth không nằm trong repository học viên, vì vậy chưa thể chạy
`src.evaluate`, chưa có số chính thức cho Recall@20/Precision@20 và chưa được
tuyên bố PoC tốt hơn baseline. Khi có overlay `gt/labels.csv`, chạy:

```bash
python -m src.evaluate --track t02 --pred out/baseline/ranked_review.csv --run-name baseline --out reports/metrics_baseline.json
python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --run-name poc --out reports/metrics_poc.json
python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
```

Không thay đổi candidate pool, split, budget, seed, trọng số hoặc threshold
sau khi xem kết quả eval.
