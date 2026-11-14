# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Điền đầy đủ, cụ thể, không viết chung chung. Mọi con số phải lấy từ file do script sinh ra
> (`reports/metrics_*.json`, `reports/table1_baseline_vs_poc.md`) — không gõ tay, không làm tròn mất đơn vị.
> 3–5 trang (hoặc README + report.md tương đương).

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G04 |
| Challenge | T02 · Raw QC Triage: ảnh mờ, lóa và thiếu sáng |
| Thành viên (5–6) + vai trò | 1. VuTuyetTrinh + LuongHoangBaoTran (Lead/Integrator) · 2. VuTuyetTrinh + LuongHoangBaoTran (Data & fixtures) · 3. LuongHoangBaoTran (Core algorithm — author commit `015cc26`) · 4. LuongHoangBaoTran (QA/metric) · 5. VuTuyetTrinh (Review + report + config) · 6. không có (nhóm 2 người) |
| Git URL | https://github.com/Trintrin0408/K5-Day6-L2-VuTuyetTrinh-2A202603164-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | chưa tạo — `make tag-demo` (hoặc `git tag demo-180m <sha> && git push origin demo-180m`) |
| Tag `final-24h` (commit) | chưa tạo — `make tag-final` sau commit cuối |
| Deadline (giờ VN) | ____ (nhóm điền: giờ bắt đầu lab + 24h; commit PoC `015cc26` lúc 2026-11-14 16:47 +07) |

## 01 · Problem statement

- **Ai bị ảnh hưởng / ai chịu hậu quả khi hệ thống sai?** (1) Đội annotation/training phía sau: ảnh mờ/lóa/tối lọt qua (miss) thì đi vào tập train, gán nhãn kém và làm model yếu trong điều kiện xấu. (2) Đội thu thập hiện trường: báo nhầm (false alarm) khiến họ phải chụp lại không cần thiết, và ảnh đêm hữu ích (hard negative) bị loại. (3) Reviewer QC: thứ hạng tệ thì 20 lượt xem bị phí vào ảnh sạch.
- **Điểm nghẽn cụ thể:** mỗi lô chỉ review được B=20/96 ảnh (≈21%). Cần xếp hạng sao cho top-20 chứa nhiều ảnh lỗi thật nhất, đồng thời không đẩy ảnh đêm/cam_B bình thường lên đầu.
- **Đầu vào → đầu ra:** `images/*.jpg` (320×180) + `images.csv` (`image_id, path, camera_id, light, split`) + `manifest.csv` (sha256) → `ranked_review.csv` (`image_id, score`, 4 feature score, `reason`, `suggested_action`, `pred_action`) + `review_queue.csv` + `contact_sheet.html` (top-20) → reviewer approve/reject → `audit_log.jsonl` + `decision_log.csv` + `decision.json` (GO/HOLD/REWORK).
- **Tiêu chí GO / HOLD / REWORK (chốt trước khi chạy eval):**
  - *Mức lô ảnh (release):* chưa review top-B → **HOLD** `REVIEW_REQUIRED`; reviewer xác nhận ≥1 ảnh RECAPTURE → **REWORK** `RECAPTURE_REQUIRED`; review xong và 0 RECAPTURE → **GO** `REVIEWED_KEEP`.
  - *Mức PoC (so với baseline, khi có GT):* **GO** nếu Defect Recall@20 (eval) của PoC ≥ baseline + 0.10 **và** false alarm top-B ở slice `light=night` không cao hơn baseline; **HOLD** nếu recall tăng nhưng false alarm night tăng; **REWORK** nếu recall PoC ≤ baseline. Hiện chưa đánh giá được vì thiếu GT → trạng thái PoC = **HOLD**.
- **Giả định của nhóm (cần DPO/legal/domain owner xác nhận):** (a) fixture là ảnh synthetic CC0, không có PII; (b) nếu chuyển sang ảnh camera đường phố thật thì biển số/khuôn mặt là dữ liệu cá nhân, cần cơ sở xử lý và che mờ trước khi review; (c) ngưỡng RECAPTURE `score ≥ 0.45` và trọng số 0.45/0.25/0.20/0.10 được domain owner chấp nhận; (d) một reviewer duy nhất là đủ cho PoC (chưa đo đồng thuận giữa reviewer).

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev | 56 | `fixtures/t02_raw_qc` (`synthetic:tools/make_fixtures.py (seed 42)`) | CC0-1.0 (synthetic, generated for AI20K Day06) | Có |
| eval / heldout | 40 | `fixtures/t02_raw_qc` (`synthetic:tools/make_fixtures.py (seed 42)`) | CC0-1.0 (synthetic, generated for AI20K Day06) | Có |

- **Schema & class mapping:** `images.csv` = `image_id, path, camera_id, light, split`; `camera_id` ∈ {cam_A: 64, cam_B: 32}; `light` ∈ {day: 56, dusk: 20, night: 20}. GT (chỉ để evaluate, pipeline không đọc): `defect_type ∈ {none, blur, glare, dark, compression}`, `severity 0–2`, `is_defect`. PoC có 4 feature khớp 4 loại lỗi (`blur_score`, `glare_score`, `dark_score`, `compression_score`) và ghi tên các feature vượt 0.45 vào `reason` (vd. `blur+dark`). PoC **chưa** xuất cột `pred_defect_type` nên evaluator sẽ không tính "Defect-type accuracy".
- **Seed:** 42 · **Cách chia split:** theo **cảnh gốc** (`group_id` = `img_XX`, 24 cảnh × 4 biến thể): dev = 14 cảnh / 56 ảnh, eval = 10 cảnh / 40 ảnh, nên không có cảnh nào nằm ở cả hai split (tránh rò rỉ).
- **`manifest.csv` verified (sha256):** **có**. Lệnh: `.venv/Scripts/python -m tools.verify_manifests` → `14 manifests, 0 failing`. Ngoài ra bước 01 load của `src/pipeline.py` gọi `verify_manifest` với `strict_provenance: true` (`configs/lab.yaml`), nên lần chạy PoC chỉ thành công khi hash khớp.
- **Dữ liệu thật dùng (nếu có) và cách xây GT cho nó:** không dùng (`data/real/` chưa được giảng viên cung cấp). Nếu có, kế hoạch là lấy ảnh BDD thật, inject lỗi có log bằng `src/common/corruptions.py` để có GT, và giữ ảnh đêm thật sạch làm hard negative.

## 03 · Research & design

- **References và lý do chọn kỹ thuật** (chi tiết ở §11):
  1. Variance of Laplacian (Pech-Pacheco et al., ICPR 2000, giải thích qua PyImageSearch): đo độ nét bằng 1 số, chạy CPU, không cần weights → dùng cho `blur_score`.
  2. ACDC (Sakaridis et al., arXiv 2104.13395): ảnh đêm/sương/mưa/tuyết **có ích** cho perception, không phải ảnh lỗi → nhóm tách "tối vì là ban đêm" khỏi "thiếu sáng bất thường" (đây cũng là failure case 1).
  3. CVAT Automated QA: QA bằng cách so với tập GT/honeypot và đặt ngưỡng chất lượng → nhóm làm tương tự: xếp hạng rồi để reviewer xác nhận, mọi quyết định có audit log.
- **Sơ đồ data flow:**

```
images/*.jpg + images.csv + manifest.csv
   │ 01 load: verify sha256 (strict_provenance), GT guard (không đọc gt/)
   ▼
02 process: grayscale → LapVar, mean, frac_dark, p95, frac_saturated, blockiness 8px
   │        → blur/dark/glare/compression score ∈ [0,1]
   ▼
03 rank: score = 0.45·blur + 0.25·dark + 0.20·glare + 0.10·compression
   │     → ranked_review.csv (reason, suggested_action = RECAPTURE nếu score ≥ 0.45)
   ▼
04 review: top-B=20 → review_queue.csv + contact_sheet.html
   │       → reviewer approve/reject/escalate → review_queue_reviewed.csv
   │       → override pred_action + audit_log.jsonl
   ▼
05 decide: HOLD / REWORK / GO + reason_code + owner → decision.json, decision_log.csv
   ▼
evaluate (offline, có GT) → reports/metrics_*.json → src.compare → Bảng 1
```

- **Thành phần offline:** không dùng model/weights nào. Chỉ dùng `numpy`, `pandas`, `Pillow`, `scipy` (`scipy.ndimage.convolve` cho Laplacian) theo `requirements.txt`; chạy với `--offline`, không cần tải gì.
- **Trade-offs đã cân nhắc:**
  - *Feature thủ công vs CNN/IQA model:* chọn thủ công vì CPU, giải thích được (`reason` cho reviewer), không cần weights/license; đổi lại không bắt được lỗi cục bộ.
  - *Tổng có trọng số vs max của các feature:* tổng có trọng số ổn định hơn với ảnh lỗi nhẹ nhiều loại, nhưng làm ảnh chỉ lóa (trọng số 0.20) bị chìm (failure case 2). Dùng max sẽ cứu glare nhưng tăng false alarm ở ảnh đêm.
  - *Ngưỡng tuyệt đối vs chuẩn hoá theo `light`/`camera_id`:* bản 180 phút dùng ngưỡng tuyệt đối cho đơn giản, chấp nhận bias với ảnh night/cam_B. Chuẩn hoá theo nhóm để lại cho mốc +24h.
  - *Toàn ảnh vs ROI:* tính toàn ảnh nhanh hơn, nhưng vùng biển số cháy sáng nhỏ bị pha loãng.

## 04 · Baseline vs PoC

- Baseline (mô tả, version/config, commit): **Random baseline** `src.examples.random_baseline` (score = `ctx.rng.random()`, seed 42, không đọc pixel), chạy bằng `make baseline TRACK=t02` → `out/baseline/ranked_review.csv`; `run_info.json`: git_sha `b0ce8bf`, config_hash `17ecb00a131d`. Lưu ý: nhóm **chưa** cài baseline "một ngưỡng Laplacian toàn ảnh" như `docs/tracks/T02.md` §4 gợi ý — so sánh hiện tại là PoC vs random.
- PoC (mô tả, version/config, commit): `src/pipeline.py` (commit `015cc26`), config `configs/lab.yaml` + `configs/tracks/t02.yaml` (config_hash `6d75b2954c43`). Mỗi ảnh tính 4 feature toàn ảnh với hằng số cố định (không tune trên eval): `blur_score = 1 − LapVar/(LapVar+75)`; `dark_score` từ mean < 55 và `frac_dark`; `glare_score` từ p95 > 220 và `frac_saturated`; `compression_score` từ tỉ lệ gradient tại biên block 8 px. `score = 0.45·blur + 0.25·dark + 0.20·glare + 0.10·compression`; feature ≥ 0.45 → ghi vào `reason`; `score ≥ 0.45` → gợi ý RECAPTURE. Xếp hạng top-B=20 → `review_queue.csv` + `contact_sheet.html`.
- Cùng budget / cùng heldout / cùng seed: xác nhận **có** — cả hai chạy trên cùng `fixtures/t02_raw_qc` (96 ảnh, cùng `manifest.csv`), B=20, `--seed 42`, `--offline` (xem `out/baseline/run_info.json`, `out/poc/run_info.json`). **Cách nhóm tự kiểm** (vì `fixtures/t02_raw_qc/gt/` chưa có → `src.evaluate` chưa chạy được, chưa có `reports/metrics_*.json`): (1) **mắt thường + tự gắn nhãn**: reviewer xem 20 ảnh top của PoC trên `contact_sheet.html`, gắn approve/reject + ghi chú → `out/poc/review_queue_reviewed.csv` (9/20 reject = RECAPTURE); (2) **metric phụ**: phân bố top-20 theo `light` / `camera_id`, median `sharpness` theo camera, `glare_score` và thứ hạng của ảnh lóa (tính từ `out/poc/ranked_review.csv`); (3) so overlap top-20 baseline với tập đã review: chỉ 4/20 ảnh trùng (2 trong đó bị reject) → **không** tính được proxy precision công bằng cho baseline.

**Bảng 1 · Baseline vs PoC & hard slices** — dán output của
`python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json`:

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| Primary: Defect Recall@B (B=20, split eval) | chưa có | chưa có | chưa có GT (`fixtures/t02_raw_qc/gt/` không tồn tại) → chưa chạy `src.evaluate`; higher = tốt |
| Hard-slice: số ảnh `light=night` trong top-20 của split eval (metric phụ, không phải GT) | 10 | 13 | +3: PoC đẩy ảnh đêm lên nhiều hơn random (xem failure case 1); N=16 |
| Review@B / miss / FP | không review | 9 RECAPTURE / 11 KEEP (nhãn mắt thường) | proxy precision PoC = 9/20 do người tự gắn nhãn, không phải GT; ảnh lóa `img_17_2` bị miss (rank 28); B=20 |
| Runtime / 100 items | 0.0815 s / 96 ảnh | 0.3777 s / 96 ảnh | PoC chậm hơn ~4.6× nhưng vẫn < 4 ms/ảnh (từ `run_info.json`); CPU=Intel64 Family 6 Model 186 |

## 05 · Evaluation protocol

- **Công thức primary metric** (cài sẵn trong `src/metrics/tracks.py::eval_t02`): chỉ lấy ảnh thuộc split `eval` (N=40), sắp theo `score` giảm dần (mergesort, ổn định).
  - **Defect Recall@B** = #ảnh `is_defect=1` nằm trong top-B / #ảnh `is_defect=1` của eval. Đơn vị = **ảnh**; ghép prediction ↔ GT theo `image_id`.
  - TP = ảnh lỗi thật trong top-B; FN = ảnh lỗi thật ngoài top-B (miss); FP = ảnh sạch trong top-B (false alarm).
  - Kèm **Precision@B** = TP / B, và **False alarm in top-B** theo từng slice `light` = ảnh sạch trong top-B / ảnh sạch của slice (lower = tốt).
- **Threshold / budget B / K và lúc chốt:** B=20 lấy từ `configs/tracks/t02.yaml` (`eval_params.budget: 20, split: eval`). Trọng số, hằng số 75 / 55 / 220 và ngưỡng RECAPTURE 0.45 được chốt trong commit `015cc26` (2026-11-14 16:47 +07), trước khi có GT. Không đổi sau khi xem kết quả. Ngưỡng RECAPTURE không ảnh hưởng Recall@B (metric chỉ dùng thứ hạng).
- **Độ bất định khi N nhỏ:** eval chỉ có 40 ảnh / 10 cảnh, nên mẫu số của Recall@B có thể chỉ cỡ 10–20 ảnh lỗi. Nhóm sẽ báo **Wilson 95% CI** cho Recall@B và Precision@B, và bootstrap theo **cảnh** (resample 10 cảnh, 1000 lần, seed 42) cho Δ PoC − baseline. Chỉ kết luận PoC tốt hơn khi CI của Δ không chứa 0. Với các metric phụ hiện có (night 10 → 13 trong top-20) thì N quá nhỏ để kết luận thống kê, chỉ dùng làm dấu hiệu.
- **Lệnh evaluate chính xác** (chạy được khi có `fixtures/t02_raw_qc/gt/labels.csv`):
  ```bash
  python -m src.evaluate --track t02 --pred out/baseline/ranked_review.csv --run-name baseline --out reports/metrics_baseline.json
  python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv      --run-name poc      --out reports/metrics_poc.json
  python -m src.compare reports/metrics_baseline.json reports/metrics_poc.json --out reports/table1_baseline_vs_poc.md
  ```

## 06 · Result slices

| Slice | N | Baseline | PoC | Ghi chú |
|---|---|---|---|---|
| `light=night`, top-20 trên split eval (metric phụ) | 16 | 10/20 | 13/20 | PoC gắn `dark` cho 18/20 ảnh night (dark_score median 0.587), nên ảnh đêm bình thường cũng bị đẩy lên |
| `camera_id=cam_B`, top-20 trên toàn bộ 96 ảnh (metric phụ) | 32 | 6/20 | 8/20 | cam_B chiếm 33% dữ liệu nhưng 40% top-20 PoC; median sharpness cam_B 294 vs cam_A 928 |

- Failure case 1 (ảnh/metadata + root cause): **Ảnh đêm bị báo lỗi hết.** 18/20 ảnh `light=night` có `dark_score ≥ 0.45` → `reason=dark` (vd. `img_01_0`, `img_01_1`, `img_13_0`, `img_18_0`, rank 30–45); trên split eval, 13/20 ảnh top-20 là night. Khi review, reviewer giữ (approve) ảnh đêm `img_06_2`, chỉ reject `img_01_2` vì "tối bất thường so với ảnh đêm cùng cảnh (`img_01_0`)"; với `img_18_3`, `img_13_3` reviewer ghi "chỉ bị mờ, không tối — nhãn dark là báo thừa". Root cause: ngưỡng tối tuyệt đối (mean < 55) không chuẩn hoá theo `light`, nên "tối vì là ban đêm" bị coi giống "thiếu sáng bất thường".
- Failure case 2: **Glare cục bộ bị bỏ qua.** `img_17_2` (cam_A, day, eval) có `glare_score = 1.0`, `frac_saturated = 0.241` (cao nhất bộ) nhưng `score = 0.262`, rank 28 → nằm ngoài B=20. Root cause: glare chỉ chiếm trọng số 0.20 trong tổng có trọng số, nên ảnh lóa nặng nhất vẫn có score thấp hơn mọi ảnh blur; thêm nữa feature được tính trên toàn ảnh, vùng cháy sáng nhỏ (biển số) bị pha loãng (vd. `img_22_3`: `frac_saturated = 0.016`, rank 58 — cần kiểm thêm bằng mắt). **cam_B mềm:** blur_score median cam_B 0.204 vs cam_A 0.075 do hằng số 75 dùng chung mọi camera, nên ảnh cam_B bình thường bị cộng điểm nền cao hơn (ảnh đêm cam_B xếp trên ảnh đêm cam_A). Trong top-20 reviewer chưa thấy FP rõ ràng của cam_B (`img_09_2`, `img_21_2` cam_B, sharpness ≈ 1.7 là mờ thật), nhưng thiên lệch này có thể gây báo nhầm ở ngưỡng thấp hơn. Ngoài ra nhãn tự gắn chưa nhất quán: `img_15_2` (sharpness 1.91) được approve trong khi `img_09_2` (1.66) bị reject.
- Latency / compute (máy, CPU, ms/item): Windows 11 (10.0.26300), Intel64 Family 6 Model 186, Python 3.13.1; PoC 0.3777 s / 96 ảnh ≈ 3.9 ms/ảnh; baseline 0.0815 s / 96 ảnh ≈ 0.85 ms/ảnh.

## 07 · Human & decision

- Review queue (file, B, cách ưu tiên): `out/poc/review_queue.csv` + `out/poc/contact_sheet.html`, B=20, ưu tiên theo `score` giảm dần; kết quả review ở `out/poc/review_queue_reviewed.csv` (reviewer VuTuyetTrinh, 20/20 ảnh).
- Cách override + audit log (`out/audit_log.jsonl`): `review()` trong `src/pipeline.py` map approve → KEEP, reject → RECAPTURE, escalate → HOLD vào `pred_action`; mỗi quyết định ghi 1 dòng `review:<decision>` (actor, item_id, after, reason) vào `out/poc/audit_log.jsonl`.
- Decision policy + `reason_code` + owner: chưa review → HOLD / `REVIEW_REQUIRED`; có ≥1 RECAPTURE → REWORK / `RECAPTURE_REQUIRED`; không có → GO / `REVIEWED_KEEP`. Owner = `owner` trong `configs/lab.yaml` ("Vu Tuyet Trinh - Reviewer"). Lần chạy cuối: REWORK / `RECAPTURE_REQUIRED` — "9 reviewed image(s) require recapture" (`out/poc/decision.json`). Baseline luôn HOLD / `BASELINE_ONLY`.
- Khi nào HOLD/REWORK thay vì tự động release: HOLD khi top-20 chưa được người review; REWORK khi reviewer xác nhận ≥1 ảnh cần chụp lại. Pipeline không bao giờ tự GO khi chưa review.

## 08 · Reproduce & tests

```bash
make setup                                   # hoặc: python -m venv .venv && pip install -r requirements.txt
make baseline TRACK=t02                      # random baseline → out/baseline/
python -m src.main --config configs/lab.yaml --track t02 --output out/poc --run-name poc --offline --seed 42   # = make run TRACK=t02
python -m src.evaluate --track t02 --pred out/poc/ranked_review.csv --run-name poc --out reports/metrics_poc.json   # cần gt/
pytest -q
```

- Output của `pytest -q`: 46 passed, 39 skipped, 1 failed — `tests/test_cli.py::test_template_pipeline_fails_clearly_not_silently` (test mong pipeline template báo NotImplemented, exit 3; nay `src/pipeline.py` đã cài T02 nên trả 0).
- Máy / CPU / OS / Python: Intel64 Family 6 Model 186 / Windows 11 10.0.26300 / Python 3.13.1 · git sha: `015cc26` (lần chạy PoC), `b0ce8bf` (lần chạy baseline)

## 09 · Limitations & ethics

- **Rủi ro pháp lý / PII / license:** fixture là synthetic CC0-1.0 nên không có PII và không vướng license. Rủi ro xuất hiện khi dùng ảnh camera giao thông thật: biển số xe và khuôn mặt là dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP; GDPR nếu có chủ thể EU). Contact sheet hiển thị ảnh gốc cho reviewer, nên với ảnh thật cần che mờ biển số/mặt người trước khi đưa vào queue, giới hạn quyền xem, và không commit ảnh thật lên git. Feature "glare vùng biển số" ở bản ROI phải chạy trên vùng đã che, không lưu crop biển số.
- **Điều chưa biết; false alarms; nếu scale 10× thì sao:** chưa biết Recall@B thật vì chưa có GT. Proxy precision 9/20 chỉ do một người gắn nhãn và có điểm chưa nhất quán (`img_15_2` vs `img_09_2`). False alarm đã thấy tập trung ở ảnh night (`dark`) và có nguy cơ ở cam_B. Nếu scale 10× (~960 ảnh/lô): runtime vẫn nhỏ (~3.9 ms/ảnh → ≈ 4 s), nhưng B=20 chỉ còn ≈ 2% lô. Khi đó cần B tỉ lệ theo lô, hoặc tự KEEP các ảnh score rất thấp, và thêm reviewer thứ hai để đo đồng thuận. Camera/điều kiện mới (out-of-domain) sẽ làm hằng số cố định lệch thêm.
- **Không tuyên bố "đạt GDPR / luật Việt Nam" từ checklist tự động; giả định cần DPO/legal xác nhận:** nhóm **không** tuyên bố tuân thủ. Các giả định cần DPO/legal xác nhận: (1) ảnh synthetic không cần đánh giá tác động; (2) với ảnh thật, che mờ biển số/mặt là đủ để reviewer nội bộ xem; (3) thời hạn lưu `audit_log.jsonl` (có tên reviewer) và ai được xem; (4) mục đích "QC dữ liệu huấn luyện" là cơ sở xử lý hợp lệ.
- **Kế hoạch cải tiến (mốc +24h):** (1) cài baseline đúng spec "một ngưỡng Laplacian toàn ảnh", chọn ngưỡng trên dev; (2) chuẩn hoá `dark_score` theo `light` (so với median cùng `light`/cùng cảnh) để sửa failure case 1; (3) hằng số blur riêng cho từng `camera_id` (fit trên dev) để sửa bias cam_B; (4) glare theo ROI/cửa sổ trượt (max `frac_saturated` cục bộ), và dùng `max(feature)` hoặc tăng trọng số glare để `img_17_2` vào top-B; (5) xuất `pred_defect_type`; (6) khi có GT: chạy `src.evaluate`, báo Wilson CI, kiểm 10 ảnh out-of-domain; (7) sửa/cập nhật test `test_template_pipeline_fails_clearly_not_silently`; (8) thêm reviewer thứ hai để đo đồng thuận.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (đối chiếu với `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| VuTuyetTrinh + LuongHoangBaoTran | Trintrin0408 <165535901+Trintrin0408@users.noreply.github.com>; lhbtran2003 <lhbtran2003@gmail.com> | Integration / CLI | `4beec4f` (`configs/lab.yaml`: group G04, owner, track t02); hai người cùng chạy `src.main` cho baseline và PoC (`out/baseline/run_info.json`, `out/poc/run_info.json`) | |
| VuTuyetTrinh + LuongHoangBaoTran | Trintrin0408 <165535901+Trintrin0408@users.noreply.github.com>; lhbtran2003 <lhbtran2003@gmail.com> | Data + GT | không có commit riêng: dùng fixture có sẵn `fixtures/t02_raw_qc` (chưa có GT); cùng kiểm provenance qua `manifest.csv` (`tools.verify_manifests`: 14 manifests, 0 failing) | |
| LuongHoangBaoTran | lhbtran2003 <lhbtran2003@gmail.com> | Core algorithm | `015cc26` feat: implement T02 raw image quality pipeline (`src/pipeline.py`, +249/−95) — git author `lhbtran2003` | |
| LuongHoangBaoTran | lhbtran2003 <lhbtran2003@gmail.com> | Metric + tests | không có commit riêng: chạy `pytest -q` (46 passed, 39 skipped, 1 failed) và tính metric phụ (top-20 theo `light` / `camera_id`) | |
| VuTuyetTrinh | Trintrin0408 <165535901+Trintrin0408@users.noreply.github.com> | Review queue + report | `4beec4f` chore(config): set group G04 and owner for T02; review 20 ảnh `out/poc/review_queue_reviewed.csv` + `out/poc/audit_log.jsonl`; viết `reports/group_report.md` | |
| Member 6 (nếu có) | — | Research / ablation / debate | không có (nhóm 2 người; phần research do VuTuyetTrinh + LuongHoangBaoTran cùng làm) | |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa (không chép nguyên văn) |
|---|---|---|
| https://pyimagesearch.com/2015/09/07/blur-detection-with-opencv/ | 2026-11-14 | Đo độ nét bằng phương sai của Laplacian (theo Pech-Pacheco et al., ICPR 2000). Là cơ sở cho `blur_score` và cho baseline "một ngưỡng Laplacian". |
| https://arxiv.org/abs/2104.13395 | 2026-11-14 | ACDC: ~8k ảnh lái xe, một nửa trong sương/đêm/mưa/tuyết, ghép với ảnh trời quang cùng cảnh. Cho thấy ảnh điều kiện xấu là dữ liệu có giá trị, không nên loại → lý do tách "đêm" khỏi "thiếu sáng". |
| https://docs.cvat.ai/docs/qa-analytics/auto-qa/ | 2026-11-14 | CVAT đo chất lượng annotation bằng cách so với job GT/honeypot và đặt ngưỡng yêu cầu. Nhóm áp dụng ý tưởng xếp hạng → người xác nhận → báo cáo có ngưỡng. |
| ISO/IEC TR 5259-6 (data quality for analytics and ML — visualization framework), trang iso.org | ____ | Được `docs/tracks/T02.md` dẫn làm tài liệu gốc; nhóm chưa truy cập được (iso.org trả 403) nên chưa dùng nội dung. |

---

**Bảng 3 · Checklist chốt khi nộp**

- [ ] Link repo và tag cuối cùng trong README; input mẫu không chứa PII thật. *(input synthetic, không PII ✔; tag chưa tạo)*
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [ ] Có baseline/PoC metrics, ≥1 failure case, reviewer evidence, decision log. *(đã có failure case, reviewer evidence, decision log; **thiếu** `reports/metrics_*.json` vì chưa có GT)*
- [x] Có license/source provenance, data splits, seed, offline environment, GT/eval N.
- [ ] Mỗi thành viên có ≥1 commit thực chất và được nêu minh bạch trong bảng trên. *(Trintrin0408: `4beec4f` chỉ là config; lhbtran2003: `015cc26`)*
