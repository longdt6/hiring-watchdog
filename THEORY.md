# Hiring Watchdog — Lý Thuyết Nền Tảng

> **Mục đích của file này**: Hiểu lý thuyết đằng sau các thuật toán phát hiện bất thường. Không chỉ code — phải biết tại sao nó hoạt động.

---

## Mục Lục

1. [Time Series Anomaly Detection — Tổng quan](#1-time-series-anomaly-detection--tổng-quan)
2. [Z-Score — Phát hiện điểm bất thường](#2-z-score--phát-hiện-điểm-bất-thường)
3. [CUSUM — Phát hiện dịch chuyển mặt bằng](#3-cusum--phát-hiện-dịch-chuyển-mặt-bằng)
4. [Exponential Moving Average (EMA) — Đường nền thích nghi](#4-exponential-moving-average-ema--đường-nền-thích-nghi)
5. [Seasonal Decomposition (STL) — Xử lý tính mùa vụ](#5-seasonal-decomposition-stl--xử-lý-tính-mùa-vụ)
6. [Change Point Detection — Tìm chính xác thời điểm thay đổi](#6-change-point-detection--tìm-chính-xác-thời-điểm-thay-đổi)
7. [Cold Start Problem — Phát hiện khi chưa có dữ liệu lịch sử](#7-cold-start-problem--phát-hiện-khi-chưa-có-dữ-liệu-lịch-sử)

---

## 1. Time Series Anomaly Detection — Tổng Quan

### Định nghĩa đơn giản

**Time Series** là chuỗi dữ liệu được ghi nhận theo thời gian: $X = \{x_1, x_2, ..., x_t\}$. Ví dụ: số lượng job mới của FPT mỗi tuần trong 2 năm qua.

**Anomaly Detection** là bài toán tìm ra những điểm/thời đoạn mà dữ liệu "không giống bình thường". Có 3 kiểu bất thường chính:

```
TYPE A: POINT ANOMALY        TYPE B: LEVEL SHIFT        TYPE C: TREND CHANGE
    ●                                                   /
    │                         ───────────────           /
────┼──────────────        ────┘            ───────────
    │          ●                           /
    │                                     /
```

| Kiểu | Tên | Ý nghĩa thực tế |
|------|-----|----------------|
| A — Point Anomaly | Điểm đơn lẻ | Một tuần có event đặc biệt, sau đó về bình thường |
| B — Level Shift | Dịch chuyển mặt bằng | Công ty mở rộng, mặt bằng tuyển dụng tăng và giữ ở mức mới |
| C — Trend Change | Thay đổi xu hướng | Tốc độ tăng thay đổi: đang tăng chậm → tăng nhanh |

→ **Bài toán Hiring Watchdog chủ yếu là Type B + C**: phát hiện khi nào một công ty nâng mặt bằng tuyển dụng lên hẳn mức mới, và duy trì ở đó. Không phải chỉ một ngày đột biến rồi thôi.

### Tại sao quan trọng?

Nếu chỉ nhìn số job hôm nay (ví dụ: 15 jobs), bạn không biết nó là "bình thường" hay "bất thường". Cần so sánh với **lịch sử** của chính công ty đó. 15 jobs với FPT (thường đăng 80 jobs/tuần) là bình thường. 15 jobs với một công ty mới toanh là TÍN HIỆU MẠNH.

### Đọc thêm

- **Bài viết ngắn**: [Introduction to Anomaly Detection in Time Series](https://towardsdatascience.com/anomaly-detection-for-dummies-15f148e859c1)
- **Sách**: *"Outlier Analysis"* — Charu C. Aggarwal (2017), **Chapter 8: Time Series and Streaming Outlier Detection**

---

## 2. Z-Score — Phát Hiện Điểm Bất Thường

### Định nghĩa đơn giản

Z-Score đo xem một giá trị **lệch bao nhiêu độ lệch chuẩn** so với trung bình:

$$Z = \frac{x - \mu}{\sigma}$$

- $\mu$ = trung bình lịch sử
- $\sigma$ = độ lệch chuẩn lịch sử
- $Z = 2.0$ → giá trị hiện tại cao hơn trung bình 2 lần độ lệch chuẩn (~2.3% xác suất xảy ra ngẫu nhiên, nếu dữ liệu phân phối chuẩn)

**Ngưỡng phổ biến**:

| \|Z\| > | Xác suất ngẫu nhiên | Mức cảnh báo |
|---------|---------------------|-------------|
| 2.0 | ~2.3% | Yellow |
| 2.5 | ~0.6% | Orange |
| 3.0 | ~0.1% | Red |

**Rolling Z-Score** (dùng trong Hiring Watchdog): thay vì tính $\mu$ và $\sigma$ trên toàn bộ lịch sử, chỉ tính trên $w$ tuần gần nhất (ví dụ 4-8 tuần). Nhờ vậy baseline thích nghi với trend dài hạn — khi công ty tăng trưởng tự nhiên, baseline cũng tăng theo, chỉ bắt phần tăng VƯỢT TREND.

### Tại sao quan trọng?

Z-Score là thuật toán đơn giản nhất để phát hiện bất thường. Nó trả lời câu hỏi: "Hôm nay có khác thường không?" Tuy nhiên Z-Score có điểm yếu: chỉ phát hiện **điểm đơn lẻ**, không phát hiện được sự tích lũy của nhiều sai lệch nhỏ. Cần bổ sung bằng CUSUM.

### Đọc thêm

- **Bài viết ngắn**: [Z-Score for Anomaly Detection](https://towardsdatascience.com/z-score-for-anomaly-detection-d98b00003c6a)
- **Sách**: *"Practical Statistics for Data Scientists"* — Peter Bruce & Andrew Bruce (2017), **Chapter 1: Exploratory Data Analysis** (phần Percentiles and Boxplots)

---

## 3. CUSUM — Phát Hiện Dịch Chuyển Mặt Bằng

### Định nghĩa đơn giản

**CUSUM (Cumulative Sum)** tích lũy các sai lệch nhỏ liên tiếp thành một tín hiệu lớn. Ý tưởng: nếu mỗi tuần công ty đăng nhiều hơn bình thường một chút, Z-Score từng tuần có thể không vượt ngưỡng — nhưng nếu xu hướng này kéo dài 5-6 tuần, thì đó thực sự là level shift.

**Công thức**:

$$S_0 = 0$$
$$S_t = \max(0, S_{t-1} + (x_t - \mu_0) - K)$$

Trong đó:
- $x_t$ = giá trị hiện tại (số job tuần này)
- $\mu_0$ = trung bình lịch sử (baseline)
- $K$ = **dung sai** (allowance) — thường $K = \delta/2$, với $\delta$ là mức shift tối thiểu muốn phát hiện
- $\max(0, \cdot)$ = chỉ quan tâm shift dương (tăng), bỏ qua giảm
- **Báo động khi** $S_t > H$, với $H$ là ngưỡng tích lũy

**Trực quan hóa**:

```
Tuần  x_t   x_t-μ₀-K   CUSUM (S_t)      Minh họa
───────────────────────────────────────
1     3     3-3-0.5=-0.5  max(0,0-0.5)=0   ·
2     2     2-3-0.5=-1.5  max(0,0-1.5)=0   ·
3     4     4-3-0.5=+0.5  max(0,0+0.5)=0.5 ▏
4     5     5-3-0.5=+1.5  max(0,0.5+1.5)=2 ▍
5     6     6-3-0.5=+2.5  max(0,2+2.5)=4.5 █▌
6     5     5-3-0.5=+1.5  max(0,4.5+1.5)=6 ██
7     7     7-3-0.5=+3.5  max(0,6+3.5)=9.5 ███▌ ← Vượt H=5, ALERT!
```

Nhận xét: từng tuần 3, 4, 5 riêng lẻ không đủ để Z-Score báo động — nhưng CUSUM tích lũy 5 tuần liên tục cao hơn baseline và phát hiện ra pattern.

### Tại sao quan trọng?

Trong tuyển dụng, hiếm khi công ty đăng 80 job trong 1 ngày (point anomaly). Thường thì họ tăng dần: 5 → 8 → 12 → 15 → 20 jobs/tuần. CUSUM phát hiện sớm hơn Z-Score trong trường hợp này — thường sớm hơn 2-3 tuần. Đây là khác biệt giữa **"biết khi đang xảy ra"** và **"biết khi đã xong".**

### Đọc thêm

- **Bài viết ngắn**: [CUSUM: A Simple Yet Powerful Change Detection Method](https://towardsdatascience.com/cusum-a-simple-yet-powerful-change-detection-method-53d02e16aeb8)
- **Sách**: *"Introduction to Statistical Process Control"* — Douglas C. Montgomery (2019), **Chapter 9: CUSUM and EWMA Control Charts**

---

## 4. Exponential Moving Average (EMA) — Đường Nền Thích Nghi

### Định nghĩa đơn giản

EMA là cách tính trung bình mà **điểm càng gần hiện tại càng có trọng số cao**. Khác với trung bình đơn giản (mọi điểm bằng nhau), EMA "nhớ" quá khứ nhưng ưu tiên hiện tại.

$$\text{EMA}_t = \alpha \cdot x_t + (1 - \alpha) \cdot \text{EMA}_{t-1}$$

Với $\alpha = \frac{2}{w + 1}$ (quy ước chuẩn).

| $\alpha$ | Trọng số 5 tuần gần nhất | Phản ứng với thay đổi | Phù hợp cho |
|----------|-------------------------|----------------------|-------------|
| 0.3 (w=6) | ~86% | Nhanh | Phát hiện sớm |
| 0.1 (w=19) | ~41% | Chậm | Baseline ổn định |

### Tại sao quan trọng?

Hiring Watchdog dùng EMA để xây dựng baseline cho mỗi công ty. Nếu dùng trung bình đơn giản, một spike từ 6 tháng trước vẫn ảnh hưởng đến baseline hôm nay — gây trễ và false negative. EMA giúp baseline thích nghi nhanh hơn với thực tế mới.

### Đọc thêm

- **Bài viết ngắn**: [Exponential Moving Average Explained](https://towardsdatascience.com/moving-averages-in-python-16170e209fe2)
- **Sách**: *"Forecasting: Principles and Practice"* — Hyndman & Athanasopoulos (ấn bản 3, online free), **Chapter 8: Exponential Smoothing** (https://otexts.com/fpp3/)

---

## 5. Seasonal Decomposition (STL) — Xử Lý Tính Mùa Vụ

### Định nghĩa đơn giản

Dữ liệu theo thời gian thường có 3 thành phần:

$$X_t = T_t + S_t + R_t$$

| Thành phần | Ký hiệu | Ý nghĩa |
|-----------|---------|---------|
| Trend | $T_t$ | Xu hướng dài hạn (tăng trưởng tự nhiên của ngành IT) |
| Seasonal | $S_t$ | Mẫu hình lặp lại theo chu kỳ (tháng 9 luôn là mùa cao điểm tuyển dụng) |
| Residual | $R_t$ | Phần dư — **đây mới là thứ cần phát hiện anomaly** |

**STL (Seasonal-Trend decomposition using LOESS)** là phương pháp tách 3 thành phần này. Sau khi tách, anomaly detection chạy trên $R_t$ thay vì $X_t$ gốc. Nhờ vậy không bị false alarm vào tháng 9 (mùa cao điểm tự nhiên).

### Tại sao quan trọng?

Tuyển dụng IT có tính mùa vụ rõ rệt:
- **Tháng 1-2**: Sau Tết, cao điểm thay đổi nhân sự, lập kế hoạch năm mới
- **Tháng 6-8**: Sinh viên tốt nghiệp, nhiều junior position
- **Tháng 9-10**: Push Q4, chạy deadline cuối năm
- **Tháng 11-12**: Đóng budget, ít tuyển

Nếu không tách seasonal, hệ thống sẽ báo động mỗi tháng 9 vì "job tăng 40% so với tháng 8" — trong khi đó là mùa vụ bình thường. False positive làm giảm niềm tin vào hệ thống.

### Đọc thêm

- **Bài viết ngắn**: [STL Decomposition: A Practical Guide](https://towardsdatascience.com/stl-decomposition-how-to-do-it-from-scratch-b0606e82ae8a)
- **Sách**: *"Forecasting: Principles and Practice"* — Hyndman & Athanasopoulos, **Chapter 3: Time Series Decomposition** (https://otexts.com/fpp3/decomposition.html)

---

## 6. Change Point Detection — Tìm Chính Xác Thời Điểm Thay Đổi

### Định nghĩa đơn giản

Không chỉ muốn biết **"có thay đổi không"**, còn muốn biết **"thay đổi từ khi nào"**. Change Point Detection tìm thời điểm $\tau$ mà trước và sau nó, dữ liệu tuân theo 2 phân phối khác nhau.

**PELT (Pruned Exact Linear Time)** là thuật toán phổ biến nhất, tìm nhiều change points trong thời gian $O(n)$:

$$\min_{\tau_1,...,\tau_k} \left[ \sum_{i=1}^{k+1} \mathcal{C}(x_{\tau_{i-1}+1:\tau_i}) + \beta \cdot k \right]$$

- $\mathcal{C}$ = cost function (tổng bình phương sai số trong mỗi đoạn)
- $\beta$ = penalty (chống overfitting — tìm quá nhiều change point)

### Tại sao quan trọng?

Biết **chính xác** thời điểm bắt đầu mass hiring giúp:
- Đánh giá bạn đã bỏ lỡ cơ hội bao lâu
- Dự đoán xu hướng: nếu đợt này kéo dài 3-6 tháng (như Vinsmart 9/2025-6/2026), bạn còn thời gian để apply
- Phân biệt: đây là đợt tuyển dụng thứ 2 trong năm hay đợt đầu tiên?

### Đọc thêm

- **Bài viết ngắn**: [Change Point Detection in Time Series](https://techrando.com/2019/08/14/a-brief-introduction-to-change-point-detection-using-python/)
- **Sách**: *"Bayesian Analysis of Change Point Problems"* — Jie Chen & Arjun K. Gupta (2011), **Chapter 2: The Univariate Normal Model**

---

## 7. Cold Start Problem — Phát Hiện Khi Chưa Có Dữ Liệu Lịch Sử

### Định nghĩa đơn giản

Tất cả thuật toán trên (Z-Score, CUSUM, STL) đều cần **historical data** để xây dựng baseline. Nhưng với công ty mới thành lập — như VinSmart Future — không có lịch sử. $x_t$ từ 0 → 20 jobs. Không tính được Z-Score vì $\sigma = 0$ (lịch sử toàn số 0).

Đây gọi là **Cold Start Problem** trong anomaly detection.

**Giải pháp**: Thay vì dùng statistical methods (cần history), dùng **rule-based scoring** dựa trên đặc điểm của chính đợt tuyển dụng:

| Tín hiệu | Trọng số | Logic |
|----------|---------|-------|
| Số lượng job tuyệt đối (≥20 jobs) | 0.35 | Công ty mới mà đăng 20 jobs là RẤT LẠ |
| Độ đa dạng role (≥7 roles khác nhau) | 0.20 | Đang build cả team, không phải tuyển thay thế |
| Tỷ lệ Senior+ (≥50%) | 0.20 | Cần người giỏi ngay → sẵn sàng trả cao |
| Lương cao hơn market P90 (≥30%) | 0.15 | Premium pay rõ ràng |
| Xác nhận là công ty IT (≥80% role IT) | 0.10 | Lọc nhiễu (công ty không phải IT) |

### Tại sao quan trọng?

Đây là **toàn bộ lý do bạn bắt đầu dự án này**. Bạn bỏ lỡ VinSmart Future vì:
1. Không biết họ tồn tại → không có trong whitelist
2. Họ không có lịch sử → không tính được Z-Score
3. Họ mới → không ai viết bài báo về họ → Google Alerts không bắt được

Cold Start Score giải quyết cả 3 vấn đề trên: không cần whitelist, không cần history, không cần bài báo. Chỉ cần dữ liệu job posting thô.

### Đọc thêm

- **Bài viết ngắn**: [Handling the Cold Start Problem in Anomaly Detection](https://towardsdatascience.com/anomaly-detection-with-limited-historical-data-d631abed3a3e)
- **Sách**: *"Anomaly Detection Principles and Algorithms"* — Kishan G. Mehrotra et al. (2017), **Chapter 10: Ensemble Methods and Cold Start**

---

## Tài Liệu Tham Khảo Tổng Hợp

### Sách nên đọc (theo thứ tự ưu tiên)

1. **"Practical Statistics for Data Scientists"** — Peter Bruce & Andrew Bruce
   - Dễ đọc nhất, tập trung vào ứng dụng thực tế. Chương 1-2 là đủ cho nền tảng thống kê.

2. **"Forecasting: Principles and Practice"** — Hyndman & Athanasopoulos
   - Online free tại https://otexts.com/fpp3/. Kinh thánh về time series. Chương 3 (decomposition) và 8 (exponential smoothing) là cần thiết.

3. **"Introduction to Statistical Process Control"** — Douglas C. Montgomery
   - Chương về CUSUM và EWMA. Đây là gốc của mọi thuật toán phát hiện level shift trong công nghiệp.

4. **"Outlier Analysis"** — Charu C. Aggarwal
   - Toàn diện nhất về anomaly detection. Chương 8-9 tập trung vào time series.

### Online Courses (miễn phí)

- [Coursera: Anomaly Detection in Time Series Data](https://www.coursera.org/learn/anomaly-detection-time-series) — short course, 4-6 giờ

---
---

**Ghi chú**: File này là tài liệu sống. Khi implement mỗi thuật toán, đọc phần lý thuyết tương ứng trước. Không cần hiểu hết mọi công thức ngay — hiểu ý tưởng trước, chi tiết sẽ rõ dần khi code.
