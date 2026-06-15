// @ts-check
// Tất cả chuỗi hiển thị trên UI gom vào 1 file để dễ chỉnh sửa.
// Khi đổi nội dung text thì chỉ sửa file này — không cần đụng vào component.
//
// Quy ước:
//  - Chuỗi tĩnh:    string literal
//  - Có placeholder: function (params) => string
//  - Mảng cố định:   array literal (vd: tiêu đề bảng)

export const strings = {
  app: {
    title: "LPWAN MAP",
    subtitle: "v2 — Đà Nẵng pilot. Stage 1 + 200 survey points.",
    tabs: {
      home: "Trang chủ",
      map: "Bản đồ điểm đo",
      heatmap: "Bản đồ phủ sóng",
      predict: "Dự đoán",
      admin: "Gateway",
      sources: "Dữ liệu của tôi",
      adminPanel: "Quản trị",
    },
    navMenu: {
      open: "Mở menu",
      close: "Đóng menu",
    },
    errorBoundary: {
      title: "Ứng dụng gặp lỗi không mong muốn",
      hint: "Tải lại trang để tiếp tục. Lỗi đã được ghi nhận.",
      reload: "Tải lại trang",
    },
    notFound: {
      title: "Không tìm thấy trang",
      hint: "Tab này không tồn tại hoặc bạn không có quyền truy cập.",
      backHome: "Về Trang chủ",
    },
  },

  landing: {
    hero: {
      eyebrow: "Bản đồ ước lượng phủ sóng · Đà Nẵng",
      titleStart: "Bản đồ ",
      titleEm: "ước lượng",
      titleEnd: " chất lượng tín hiệu cho mạng không dây LPWAN",
      lede:
        "Tổng hợp dữ liệu khảo sát thực địa, ước lượng RSSI/SNR bằng mô hình ITU-R P.1812, hiệu chỉnh từ khảo sát, dự đoán chất lượng tín hiệu trong khu vực Đà Nẵng.",
      ctaPrimary: "Mở bản đồ ngay",
      ctaSecondary: "Cách hoạt động",
      stats: [
        { v: "1000+", k: "Điểm khảo sát thực địa" },
        { v: "10+", k: "Gateway hoạt động" },
        { v: "Đà Nẵng", k: "Khu vực thí điểm" },
      ],
      mapLive: "Live · Đà Nẵng",
      mapLayer: "Phủ sóng · Kerlink iStation AEC",
      mapLegendTitle: "RSSI (dBm)",
      mockUrl: "lora-estimate-map/#page=heatmap",
    },
    how: {
      eyebrow: "Cách hoạt động",
      title: "Từ điểm đo đến ước lượng phủ sóng toàn thành phố.",
      lede:
        "Hệ thống thu thập dữ liệu thực địa từ nhiều nguồn, chuẩn hóa, tính toán mô hình ước lượng, và cho phép truy vấn tại tại mọi địa điểm trên địa bàn thành phố Đà Nẵng.",
      steps: [
        {
          num: "01",
          title: "Thu thập",
          desc: "Dữ liệu khảo sát thực tế nạp từ ChirpStack webhook, Lpwanmapper hoặc upload CSV/JSON thủ công.",
        },
        {
          num: "02",
          title: "Chuẩn hóa",
          desc: "Lọc và xử lý dữ liệu thô để chuẩn hóa định dạng, hiệu chỉnh sai số thiết bị.",
        },
        {
          num: "03",
          title: "Ước lượng",
          desc: "Mô hình lan truyền ITU-R P.1812 có hiệu chỉnh bằng dữ liệu khảo sát, tính toán và vẽ ra bản đồ ước lượng vùng phủ tín hiệu.",
        },
        {
          num: "04",
          title: "Kết quả",
          desc: "Cung cấp bản đồ trực quan về vùng phủ mạng không dây LPWAN trên địa bàn thành phố Đà Nẵng, cùng công cụ dự đoán tín hiệu để tham khảo trước khi lắp đặt thiết bị mạng.",
        },
      ],
    },
    features: {
      eyebrow: "Tính năng",
      title: "Công cụ cho khảo sát và triển khai LPWAN tại Đà Nẵng.",
      lede:
        "Từ bản đồ tương tác đến tra cứu, dự đoán,... hệ thống hỗ trợ cho nghiên cứu, khảo sát và tham khảo dữ liệu cho mọi tệp người dùng.",
      items: [
        {
          num: "F · 01",
          title: "Bản đồ phủ sóng ước lượng",
          desc: "Bản đồ nhiệt ước lượng chất lượng tín hiệu RSSI tính bằng ITU-R P.1812, hiệu chỉnh từ dữ liệu khảo sát thực địa. Hiển thị tổng hợp tất cả gateway hoặc cô lập từng vùng phủ.",
          cta: "Mở Bản đồ phủ sóng",
          target: "heatmap",
          mockUrl: "lora-estimate-map/#page=heatmap",
        },
        {
          num: "F · 02",
          title: "Bản đồ điểm đo khảo sát thực địa",
          desc: "Mỗi marker là một phép đo thực tế, hiển thị RSSI/SNR/SF và gateway phục vụ. Nhấn vào marker để xem chi tiết thông tin.",
          cta: "Mở Bản đồ điểm đo",
          target: "map",
          mockUrl: "lora-estimate-map/#page=map",
        },
        {
          num: "F · 03",
          title: "Dự đoán tín hiệu tại vị trí cụ thể (lỗi-đang fix)",
          desc: "Chọn vị trí trên bản đồ hoặc nhập địa chỉ địa điểm trên địa bàn thành phố Đà Nẵng, hệ thống sẽ phân tích và đưa ra kết quả dự đoán về chất lượng tín hiệu tại vị trí đó.",
          cta: "Mở Dự đoán",
          target: "predict",
          mockUrl: "lora-estimate-map/#page=predict",
        },
        {
          num: "F · 04",
          title: "Theo dõi trực tiếp chuyến đi khảo sát",
          desc: "Liên kết với ChirpStack webhook để tự động cập nhật điểm đo mới nhất lên bản đồ khi đang khảo sát thực địa. Theo dõi tiến trình khảo sát theo thời gian thực.",
          cta: "Xem ngay",
          target: "map",
          mockUrl: "lora-estimate-map/#page=map",
        },
        {
          num: "F · 05",
          title: "Quản lý nguồn dữ liệu cá nhân",
          desc: "Liên kết tài khoản ChirpStack/Lpwanmapper để tải dữ liệu lên hệ thống hoặc upload CSV/JSON thủ công,... để xem trực quan dữ liệu của mình trên bản đồ.",
          cta: "Mở Dữ liệu của tôi",
          target: "sources",
          subTab: "overview",
          mockUrl: "lora-estimate-map/#page=sources&tab=overview",
        },
        {
          num: "F · 06",
          title: "Đóng góp dữ liệu cho bản đồ chung",
          desc: "Chia sẻ dữ liệu khảo sát của cá nhân vào bản đồ công khai, yêu cầu xác thực email. Càng nhiều dữ liệu, mô hình hiệu chỉnh phủ sóng ước lượng càng chính xác.",
          cta: "Đóng góp dữ liệu",
          target: "sources",
          subTab: "manage",
          mockUrl: "lora-estimate-map/#page=sources&tab=manage",
        },
      ],
    },
    faq: {
      eyebrow: "Câu hỏi thường gặp",
      title: "Trước khi bắt đầu.",
      lede:
        "Một vài câu hỏi thường gặp về công nghệ LPWAN, phạm vi hoạt động, mô hình ước lượng và dữ liệu.",
      items: [
        {
          q: "Mạng không dây LPWAN là gì?",
          a: "LPWAN (Low-Power Wide-Area Network — mạng diện rộng tiêu thụ năng lượng thấp) là họ công nghệ vô tuyến thiết kế cho thiết bị IoT gửi gói tin nhỏ trên khoảng cách xa (đơn vị km), pin dùng được nhiều năm. Các chuẩn phổ biến: LoRaWAN, Sigfox, NB-IoT.\n\nLoRa (Long Range) là kỹ thuật điều chế lớp vật lý do Semtech phát triển, dùng Chirp Spread Spectrum — CSS (tín hiệu quét tần số dạng chirp thay vì sóng mang cố định). Nhờ CSS, máy thu LoRa đạt độ nhạy tới ~ −148 dBm, kháng nhiễu Doppler và đa đường (multipath) tốt. Tham số Spreading Factor (SF7 → SF12) đánh đổi giữa tốc độ và khoảng cách: SF càng cao → đi xa hơn nhưng tốc độ chậm hơn và thời gian phát (time-on-air) dài hơn.",
        },
        {
          q: "Phạm vi hoạt động của hệ thống là gì?",
          a: "Phạm vi địa lý: tập trung vào địa giới thành phố Đà Nẵng (Hải Châu, Thanh Khê, Sơn Trà, Ngũ Hành Sơn, Liên Chiểu, Cẩm Lệ và huyện Hòa Vang). Truy vấn ngoài khu vực này có thể trả về kết quả không chính xác do thiếu dữ liệu khảo sát và mô hình địa hình (DSM — Digital Surface Model).\n\nPhạm vi kỹ thuật: tối ưu cho LoRaWAN băng tần AS923-2 áp dụng tại Việt Nam (920–923 MHz). Hệ thống tính RSSI/SNR cho cả uplink (thiết bị → gateway) và downlink (gateway → thiết bị), hỗ trợ SF7-SF12 và phân tích bottleneck giữa hai chiều. Các công nghệ LPWAN khác (NB-IoT, Sigfox) chưa được hỗ trợ.",
        },
        {
          q: "Mô hình ước lượng hoạt động thế nào? Có đáng tin cậy không?",
          a: "Mô hình lan truyền chính là ITU-R P.1812 — mô hình truyền sóng có nhận thức địa hình (terrain-aware), tính suy hao đường truyền dựa trên DSM (gồm địa hình thực + tòa nhà + tán cây). DSM được làm dày bằng land cover ESA WorldCover và polygon nhà từ OSM/Google ở những nơi có dữ liệu. Sau đó hệ thống hiệu chỉnh per-gateway noise floor (sàn nhiễu riêng từng gateway) và bias từ tập dữ liệu khảo sát thực địa.\n\nĐộ tin cậy: Có mô hình đáng tin cậy do được hiệu chỉnh trực tiếp từ dữ liệu khảo sát, nghĩa là càng nhiều dữ liệu khảo sát thì mô hình ước lượng càng chi tiết. Mô hình tiếp tục cải thiện khi có thêm dữ liệu đóng góp.",
        },
        {
          q: "Dự án này làm được gì?",
          a: "Năm nhóm chức năng chính:\n• Cung cấp bản đồ ước lượng chất lượng tín hiệu mạng LPWAN trên địa bàn thành phố Đà Nẵng để làm nguồn tham khảo.\n• Bản đồ điểm đo khảo sát thực địa với RSSI/SNR/SF và gateway phục vụ cho biết tập dữ liệu khảo sát như thế nào trên địa bàn thành phố.\n• Dự đoán chất lượng tín hiệu - click lên bản đồ hoặc nhập địa chỉ cụ thể hoặc dùng GPS để xem dự đoán về chất lượng tín hiệu tại vị trí quan tâm.\n• Quản lý nguồn dữ liệu cá nhân: liên kết ChirpStack/Lpwanmapper hoặc upload CSV/JSON, có thể đóng vai trò là nơi lưu trữ dữ liệu khảo sát.\n• Đóng góp dữ liệu vào dataset công khai để cải thiện mô hình chung, tăng độ tin cậy của mô hình cho cộng đồng người dùng.",
        },
        {
          q: "Dữ liệu khảo sát đến từ đâu, có được kiểm duyệt không?",
          a: "Ba nguồn:\n• ChirpStack webhook của người dùng đẩy gói tin qua webhook đến dự án.\n• Liên kết qua api Lpwanmapper.\n• Upload CSV/JSON thủ công.\n\nMỗi batch dữ liệu người dùng đóng góp mới đều ở trạng thái chờ duyệt và xem xét trước khi đưa vào dataset công khai dùng cho mô hình ước lượng.",
        },
        {
          q: "Tôi có thể đóng góp dữ liệu thế nào?",
          a: "Tạo tài khoản và xác thực email, sau đó vào mục \"Dữ liệu của tôi\":\n• Upload CSV/JSON trực tiếp tại \"Tải lên CSV/JSON\".\n• Hoặc liên kết tài khoản ChirpStack (webhook + API key) / Lpwanmapper để dữ liệu tự đồng bộ.\n\nBatch của bạn xuất hiện ở \"Quản lý dữ liệu\" với trạng thái chờ duyệt. Khi được duyệt, dữ liệu khảo sát của bạn sẽ tham gia vào dataset chung dùng để hiệu chỉnh cho mô hình. Càng nhiều dữ liệu khảo sát, bản đồ phủ sóng càng sát thực tế.",
        },
        {
          q: "Có cần đăng nhập để xem bản đồ không?",
          a: "Không. Bản đồ phủ sóng ước lượng, bản đồ điểm đo khảo sát, dự đoán tín hiệu tại điểm và tra cứu theo địa chỉ đều mở công khai. Chỉ các thao tác liên quan đến dữ liệu cá nhân (xem nguồn đã liên kết, upload, đóng góp, lịch sử batch) mới yêu cầu tài khoản.",
        },
      ],
    },
    cta: {
      title: "Mở bản đồ ước lượng phủ sóng cho Đà Nẵng.",
      desc: "Tham khảo chất lượng tín hiệu, dự đoán tín hiệu cho vị trí địa lý bạn quan tâm, hoặc đóng góp dữ liệu khảo sát của bạn.",
      primary: "Mở bản đồ ngay",
      secondary: "Đăng nhập đóng góp",
      secondaryLoggedIn: "Mở Nguồn dữ liệu",
    },
    footer: {
      desc:
        "Bản đồ ước lượng phủ vùng phủ sóng cho mạng không dây LPWAN.",
      cols: [
        {
          h: "Tính năng",
          items: [
            { label: "Bản đồ điểm đo", target: "map" },
            { label: "Bản đồ phủ sóng", target: "heatmap" },
            { label: "Dự đoán tín hiệu", target: "predict" },
            { label: "Danh sách Gateway", target: "admin" },
          ],
        },
        {
          h: "Tham khảo",
          items: [
            { label: "ITU-R P.1812-7", target: null },
            { label: "AS923-2 VN", target: null },
            { label: "ChirpStack v4", target: null },
            { label: "DSM Đà Nẵng", target: null },
          ],
        },
        {
          h: "Tài khoản",
          items: [
            { label: "Quản lý dữ liệu", target: "sources" },
          ],
        },
      ],
      copyright: "© 2026 LoRa Estimate Map · Đà Nẵng, Việt Nam",
      version: "Đà Nẵng pilot · build 2026.06.11",
    },
  },

  // Nhãn trạng thái coverage — dùng chung ở CoverageMap popup + PredictionView badge.
  coverageStatus: {
    strong: "Mạnh",
    marginal: "Tạm được",
    weak: "Yếu",
    no_coverage: "Không phủ",
  },

  coverageMap: {
    legend: {
      /** @param {number|undefined|null} gw */
      gatewayCount: (gw) => `${gw ?? "…"} gateway`,
      /** @param {number} sv */
      surveyCount: (sv) => `${sv} điểm đo`,
      // Nhãn từng bin RSSI (chip màu legend) đã chuyển sang
      // components/legend.js (SURVEY_RSSI_BINS) — single source of truth.
      // Legend dạng dài (component Legend nội bộ — hiện không dùng nhưng giữ
      // chuỗi để khi bật lại không bị mất đồng bộ).
      strongLong: "Mạnh (≥ -100 dBm)",
      goodLong: "Tốt (-100 đến -115)",
      weakLong: "Yếu (-115 đến -120)",
      noCoverageLong: "Không phủ (< -120)",
    },
    popup: {
      surveyTitle: "Điểm đo",
      deviceLabel: "Device",
      rssiLabel: "RSSI",
      snrLabel: "SNR",
      frequencyLabel: "Frequency",
      codeRateLabel: "Code Rate",
      timeLabel: "Time",
      gatewayConnectedLabel: "Gateway kết nối",
      /** @param {number} sf */
      sfLabel: (sf) => `Spreading Factor: SF${sf}`,
      gatewayTx: "TX",
      gatewayGain: "gain",
      gatewayAntenna: "Antenna",
      gatewayFreq: "Freq",
      gatewayAddress: "Địa chỉ",
      gatewayAddressLoading: "Đang tải địa chỉ…",
      gatewayAddressError: "Không lấy được địa chỉ",
      searchStatus: "Trạng thái",
      // Header cho popup ở tab "Dự đoán điểm".
      predictTitle: "Điểm dự đoán",
      /** @param {number} lat @param {number} lng */
      coords: (lat, lng) => `${lat.toFixed(5)}, ${lng.toFixed(5)}`,
      // Layer 1 — câu giải thích ngắn cho end-user (per business-logic §4.2).
      layer1Sentence: {
        strong: "Phủ sóng tốt — tín hiệu mạnh, truyền nhận ổn định, ít mất gói.",
        marginal: "Phủ sóng trung bình — vẫn dùng được nhưng tỉ lệ rớt gói tăng khi có nhiễu hoặc vật cản.",
        weak: "Phủ sóng yếu — sát ngưỡng thu của gateway, dễ mất gói. Nên tăng SF hoặc đặt thêm gateway gần hơn.",
        no_coverage: "Không có sóng — không có gateway nào đủ tín hiệu trong phạm vi phục vụ tại vị trí này.",
      },
      // Layer 2 — 11 mục kết quả dự đoán (RSSI, SNR, PDR, can nhiễu, SF,
      // băng thông, đa đường & che chắn, BER/FER, độ trễ, gateway, môi trường).
      fields: {
        rssi: "Cường độ tín hiệu RSSI",
        snr: "Tỷ số tín hiệu/nhiễu SNR",
        pdr: "Tỷ lệ thành công gói tin (PDR)",
        pdrSub: "ước lượng từ SNR margin",
        interference: "Mức can nhiễu",
        interferenceSub: "noise floor UL · DL",
        sf: "Hệ số trải phổ SF",
        sfMatch: "khớp khuyến nghị",
        /** @param {number} rec */
        sfRecommended: (rec) => `khuyến nghị: SF${rec}`,
        bandwidth: "Băng thông",
        bandwidthSub: "AS923-2 mặc định",
        shadowing: "Đa đường & che chắn",
        shadowingSub: "σ log-normal shadowing",
        berFer: "Tỷ lệ lỗi BER / FER",
        berFerSub: "LoRa CSS waterfall theo SNR margin",
        latency: "Độ trễ & biến động",
        /** @param {number} jitterMs */
        latencySub: (jitterMs) => `biến động ±${jitterMs.toFixed(0)} ms`,
        gateway: "Gateway kết nối",
        coveringGateways: "Số gateway phủ sóng",
        /** @param {number} n */
        coveringGatewaysSub: (n) =>
          n === 0
            ? "không gateway nào đủ tín hiệu"
            : n === 1
              ? "chỉ 1 gateway — single point of failure"
              : `${n} gateway — có dự phòng`,
        environment: "Thông số môi trường",
        environmentSub: "tần số · công suất TX · loại môi trường",
        unavailable: "BE chưa hỗ trợ",
      },
      envLabel: {
        outdoor: "Ngoài trời",
        indoor: "Trong nhà",
        indoor_deep: "Trong nhà (sâu)",
      },
      // Khoảng cách target → serving gateway (gateway có tín hiệu mạnh nhất,
      // chọn theo min(UL_margin, DL_margin), không phải nearest geographic).
      distanceToGateway: {
        /** @param {number} km */
        value: (km) => (km < 1 ? `${(km * 1000).toFixed(0)} m` : `${km.toFixed(2)} km`),
      },
      nearestGatewayNone: "không xác định",
      toggleLayer2: {
        show: "Xem chi tiết kỹ thuật ▾",
        hide: "Ẩn chi tiết ▴",
      },
      // 5 root-cause flag — "Bottleneck có thể xảy ra ở…" + nhãn dài cho từng cause.
      bottleneckCauses: {
        heading: "Bottleneck có thể xảy ra ở…",
        none: "Không phát hiện nguyên nhân rõ rệt — link healthy.",
        path_loss_high: "Suy hao đường truyền lớn (path loss > 140 dB)",
        snr_low: "Tỷ số tín hiệu/nhiễu sát ngưỡng decode (SNR margin < 3 dB)",
        interference:
          "Can nhiễu đồng kênh — noise floor uplink cao hơn nhiễu nhiệt ≥ 7 dB",
        tx_power_cap:
          "Công suất phát đã chạm trần AS923-2 (14 dBm) mà uplink vẫn là chiều yếu",
        sf_mismatch:
          "Hệ số trải phổ chọn thấp hơn mức khuyến nghị — đổi sang SF khuyến nghị để cải thiện",
      },
      copyLink: {
        label: "Sao chép liên kết",
        done: "Đã copy!",
      },
    },
    apiError:
      "Không tải được dữ liệu API. Kiểm tra api-service đang chạy chưa (http://localhost:8000/healthz).",
    tileErrorTitle: "Tile không load được",
    environmentPicker: {
      label: "Môi trường",
      
      options: [
        { value: "outdoor", label: "Ngoài trời", short: "Ngoài trời" },
        { value: "indoor", label: "Trong nhà", short: "Trong nhà" },
      ],
    },
    viewModePicker: {
      title: "Loại bản đồ",
      ariaLabel: "Chọn loại bản đồ",
      modes: {
        points: "Bản đồ điểm đo",
        heatmap: "Bản đồ nhiệt mật độ",
        estimate: "Bản đồ ước lượng",
      },
    },
    estimate: {
      panelTitle: "Bản đồ ước lượng RSSI tổng hợp",
      toggle: {
        open: "Mở bảng ước lượng",
        close: "Đóng bảng",
      },
      selector: {
        label: "Hiển thị theo gateway",
        placeholder: "Tất cả gateway (tổng hợp)",
        empty: "Chưa có gateway nào.",
      },
      legendTitle: "Cường độ tín hiệu mạnh nhất (dBm)",
      bins: {
        1: "> -100 dBm",
        2: "-105 đến -100 dBm",
        3: "-110 đến -105 dBm",
        4: "-115 đến -110 dBm",
        5: "-120 đến -115 dBm",
        6: "< -120 dBm",
      },
      notCovered: "< -130 (không phủ)",
      loadError:
        "Không tải được dữ liệu.",
    },
    urlPositionLabel: "Vị trí từ URL",
    filters: {
      contributor: {
        legend: "Hiển thị",
        community: "Bản đồ chung",
        me: "Của tôi",
        meLoggedOutHint: "Đăng nhập để xem dữ liệu của riêng bạn.",
      },
      linkedSource: {
        label: "Nguồn liên kết",
        optionAll: "Tất cả nguồn của tôi",
        errorLoad: "Không tải được danh sách nguồn.",
      },
      device: {
        label: "Thiết bị (DevEUI)",
        optionAll: "Tất cả thiết bị",
        empty: "Chưa có thiết bị nào.",
        errorLoad: "Không tải được danh sách thiết bị.",
      },
      source: {
        label: "Loại nguồn",
        optionAll: "Tất cả",
      },
      sfMulti: {
        legend: "Spreading Factor",
        optionAll: "Tất cả SF",
      },
      toggle: {
        open: "Mở bộ lọc",
        close: "Đóng bộ lọc",
        title: "Bộ lọc",
      },
      connectionLines: {
        sectionLabel: "Kết nối điểm đo - gateway",
        toggleLabel: "Hiện kết nối điểm đo-gateway",
        
      },
      realtime: {
        sectionLabel: "Theo dõi trực tiếp",
        panelToggle: {
          open: "Mở bảng theo dõi trực tiếp",
          close: "Đóng bảng theo dõi",
          title: "Theo dõi trực tiếp",
        },
        loginRequiredHint:
          "Bạn cần đăng nhập để bật theo dõi trực tiếp. Bấm để đăng nhập.",
        loginRequiredCta: "Đăng nhập để tiếp tục",
        toggleLabel: "Bật theo dõi trực tiếp",
        toggleHint:
          "Tự cập nhật điểm đo từ thiết bị trên bản đồ. Để tải dữ liệu lưu vào hệ thống, dùng nút \"Tải dữ liệu mới nhất\" trong tab Nguồn.",
        autoFollowLabel: "Tự theo dõi vị trí",
        autoFollowHint: "Tự dịch bản đồ tới điểm đo mới nhất.",
        liveBadge: "● TRỰC TIẾP",
        lastSeenLabel: "Mới nhất",
        lastSeenNever: "chưa có",
        /** @param {number} s */
        lastSeenSecondsAgo: (s) => `${s}s trước`,
        /** @param {number} m */
        lastSeenMinutesAgo: (m) => `${m} phút trước`,
        /** @param {number} n */
        sessionCounter: (n) => `Đã ghi nhận ${n} điểm`,
        viewButton: "Xem",
        stopButton: "Dừng",
        sourcePickerLabel: "Nguồn",
        sourcePickerPlaceholder: "— Chưa chọn nguồn —",
        sourcePickerNoActive:
          "Chưa có nguồn nào ở trạng thái Đang dùng. Vào trang Nguồn dữ liệu để thêm/bật.",
        sourcePickerErrorLoad: "Không tải được danh sách nguồn.",
      },
      timeRange: {
        legend: "Khoảng thời gian",
        presets: {
          all: "Tất cả",
          "24h": "24 giờ qua",
          "7d": "7 ngày qua",
          "30d": "30 ngày qua",
        },
      },
      rssi: {
        legend: "RSSI (dBm)",
        unit: "dBm",
      },
      snr: {
        legend: "SNR (dB)",
        unit: "dB",
      },
      clear: "Xoá",
    },
    predictPanel: {
      title: "Dự đoán",
      toggle: {
        open: "Mở bảng dự đoán",
        close: "Đóng bảng",
      },
      subTabs: {
        single: "Click chọn",
        address: "Nhập địa chỉ",
      },
      hint: "Click lên bản đồ để chọn điểm",
      latLabel: "Vĩ độ",
      lngLabel: "Kinh độ",
      empty: "—",
      submit: "Dự đoán",
      submitting: "Đang dự đoán…",
      error: "Dự đoán thất bại — thử lại.",
      clearAll: "Xoá tất cả điểm dự đoán",
      gpsButton: "Dùng vị trí của tôi (GPS)",
      gpsLocating: "Đang định vị…",
      gpsPermissionDenied:
        "Trình duyệt từ chối quyền truy cập vị trí. Bật quyền vị trí cho trang này rồi thử lại.",
      gpsUnavailable:
        "Không lấy được vị trí. Kiểm tra GPS thiết bị / kết nối mạng rồi thử lại.",
      gpsTimeout: "Quá thời gian định vị. Thử lại ở nơi thoáng (gần cửa sổ).",
      gpsUnsupported: "Trình duyệt không hỗ trợ định vị GPS.",
      gpsGenericError: "Định vị GPS lỗi không xác định.",
      addressTab: {
        label: "Địa chỉ",
        placeholder: "VD: 32 Cao Thắng, Hải Châu, Đà Nẵng",
        hint: "Nhập địa chỉ cụ thể vị trí cần dự đoán.",
        submit: "Tìm vị trí",
        submitting: "Đang tra cứu…",
        error: "Tra cứu thất bại — thử lại.",
      },
    },
  },

  addressSearch: {
    placeholder: "Nhập địa chỉ hoặc tọa độ…",
    ariaLabel: "Địa chỉ hoặc toạ độ",
    submit: "Tra",
    submitPending: "…",
    networkError: "Lỗi kết nối API",
    gpsTitle: "Dùng vị trí của tôi (GPS)",
    gpsAria: "Lấy vị trí GPS",
    gpsUnsupported: "Trình duyệt không hỗ trợ định vị.",
    gpsDenied: "Bạn đã từ chối quyền định vị.",
    gpsUnavailable: "Không lấy được vị trí — vui lòng thử lại.",
    gpsTimeout: "Hết thời gian chờ định vị.",
    gpsPending: "Đang lấy vị trí…",
  },

  predictForm: {
    presets: [
      { label: "Đà Nẵng (gần GW)", lat: 16.115, lng: 108.278 },
      { label: "TP.HCM (gần GW)", lat: 10.7717, lng: 106.7042 },
      { label: "Hà Nội (gần GW)", lat: 21.0303, lng: 105.8125 },
      { label: "Cà Mau (xa GW)", lat: 9.179, lng: 105.15 },
    ],
    fields: {
      lat: "Vĩ độ (°)",
      lng: "Kinh độ (°)",
      sf: "Spreading Factor",
    },
    submit: "Dự đoán",
    submitPending: "Đang dự đoán…",
    errorCodeLabel: "code",
  },

  predictionView: {
    title: "Kết quả dự đoán",
    fields: {
      rssi: "Cường độ tín hiệu thu (RSSI)",
      snr: "Tỷ lệ tín hiệu trên nhiễu (SNR)",
      pdr: "Tỷ lệ thành công gói tin (PDR)",
      pdrSub: "ước lượng từ SNR margin (LoRa CSS)",
      interference: "Mức độ can nhiễu",
      interferenceSub: "noise floor UL per-gateway · DL thermal",
      sf: "Hệ số trải phổ (SF)",
      /** @param {number} recommended */
      sfRecommended: (recommended) => `khuyến nghị: SF${recommended}`,
      sfMatch: "khuyến nghị: phù hợp",
      bandwidth: "Băng thông",
      bandwidthSub: "kênh AS923-2 mặc định",
      shadowing: "Đa đường & che chắn",
      shadowingSub: "σ log-normal shadowing",
      berFer: "Tỷ lệ lỗi bit/khung (BER/FER)",
      berFerSub: "LoRa CSS waterfall theo SNR margin",
      latency: "Độ trễ & biến động",
      /** @param {number} jitterMs */
      latencySub: (jitterMs) => `biến động ±${jitterMs.toFixed(0)} ms`,
      gateway: "Gateway kết nối",
      environment: "Thông số môi trường ảnh hưởng",
      environmentSub: "tần số · công suất TX · loại môi trường",
      unavailable: "BE chưa hỗ trợ",
    },
    layer1Sentence: {
      strong: "Phủ sóng tốt — tín hiệu mạnh, truyền nhận ổn định, ít mất gói.",
      marginal:
        "Phủ sóng trung bình — vẫn dùng được nhưng tỉ lệ rớt gói tăng khi có nhiễu hoặc vật cản.",
      weak:
        "Phủ sóng yếu — sát ngưỡng thu của gateway, dễ mất gói. Nên tăng SF hoặc đặt thêm gateway gần hơn.",
      no_coverage:
        "Không có sóng — không có gateway nào đủ tín hiệu trong phạm vi phục vụ tại vị trí này.",
    },
    gatewayNone: "không xác định",
    environmentLabel: {
      outdoor: "Ngoài trời",
      indoor: "Trong nhà",
      indoor_deep: "Trong nhà (sâu)",
    },
  },

  adminGateways: {
    title: "Quản lý Gateway",
    addButton: "+ Thêm gateway",
    loading: "Đang tải…",
    listError: "Không tải được danh sách gateway.",
    detailError: "Không tải được dữ liệu gateway.",
    emptyState: "Chưa có gateway. Thêm mới để bắt đầu.",
    tableHeaders: [
      "STT",
      "Code",
      "Name",
      "Lat",
      "Lon",
      "AGL (m)",
      "Gain (dBi)",
      "TX (dBm)",
      "Freq (MHz)",
      "Trạng thái",
      "",
    ],
    state: {
      online: "Online",
      offline: "Offline",
      never_seen: "Chưa từng kết nối",
      unknown: "Không rõ",
      lastSeenPrefix: "Lần cuối: ",
      lastSeenNever: "Chưa từng",
    },
    editButton: "Sửa",
    editTitle: "Sửa gateway",
    createTitle: "Thêm gateway",
    fields: {
      code: "Code",
      name: "Tên",
      id: "ID",
      lat: "Lat",
      lon: "Lon",
      latitude: "Latitude",
      longitude: "Longitude",
      altitude: "Altitude (m)",
      antennaHeight: "Antenna height (m)",
      antennaGain: "Antenna gain (dBi)",
      txPower: "TX power (dBm)",
      frequency: "Frequency (MHz)",
    },
    cancel: "Hủy",
    save: "Lưu",
    savePending: "Đang lưu…",
    create: "Tạo",
    createPending: "Đang tạo…",
    etagMismatchHint: "Đóng dialog và mở lại để lấy phiên bản mới nhất.",
    etagMissingAlert: "Server không trả ETag. Reload và thử lại.",
    etagMissingTitle: "Không thể lưu",
    ifMatchLabel: "If-Match",
    modalCloseAria: "Đóng",
    tabs: {
      manage: "Quản lý gateway",
      pending: "Gateway chờ duyệt",
      create: "Tạo mới gateway",
    },
    pending: {
      title: "Gateway chờ duyệt",
      loading: "Đang tải…",
      listError: "Không tải được danh sách gateway chờ duyệt.",
      emptyState: "Không có gateway nào đang chờ duyệt.",
      tableHeaders: [
        "STT",
        "Code",
        "Tên",
        "Lat",
        "Lon",
        "Tần số",
        "Nguồn",
        "Người đóng góp",
        "Gửi lúc",
        "",
      ],
      approveButton: "Phê duyệt",
      rejectButton: "Từ chối",
      approving: "Đang duyệt…",
      rejecting: "Đang từ chối…",
      approveSuccess: "Đã phê duyệt. {n} điểm đo được liên kết.",
      rejectNotePrompt: "Lý do từ chối (tùy chọn):",
    },
  },

  auth: {
    login: {
      title: "Đăng nhập",
      subtitle: "Dùng email + mật khẩu đã đăng ký.",
      emailLabel: "Email",
      passwordLabel: "Mật khẩu",
      submit: "Đăng nhập",
      submitPending: "Đang đăng nhập…",
      switchToRegister: "Chưa có tài khoản? Đăng ký",
    },
    register: {
      title: "Đăng ký",
      subtitle: "Mật khẩu tối thiểu 8 ký tự.",
      emailLabel: "Email",
      passwordLabel: "Mật khẩu",
      submit: "Đăng ký",
      submitPending: "Đang tạo tài khoản…",
      switchToLogin: "Đã có tài khoản? Đăng nhập",
      successHint: "Tài khoản đã tạo — đăng nhập để tiếp tục.",
    },
    forgot: {
      title: "Quên mật khẩu",
      subtitle: "Nhập email — chúng tôi sẽ gửi link đặt lại mật khẩu (TTL 30 phút).",
      emailLabel: "Email",
      submit: "Gửi link đặt lại",
      submitPending: "Đang gửi…",
      // Always-200 message: không xác nhận email tồn tại. Nội dung ánh xạ
      // backend response (204 trên cả 2 nhánh user-exists vs not-exists).
      successHint:
        "Nếu email này thuộc về một tài khoản, link đặt lại đã được gửi. Kiểm tra hộp thư (và spam).",
      switchToLogin: "Nhớ mật khẩu? Đăng nhập",
      // Link "Quên mật khẩu?" hiển thị dưới form Login.
      linkFromLogin: "Quên mật khẩu?",
    },
    reset: {
      title: "Đặt lại mật khẩu",
      subtitle:
        "Nhập mật khẩu mới. Sau khi đặt lại, mọi phiên đăng nhập hiện tại sẽ bị thu hồi.",
      newPasswordLabel: "Mật khẩu mới",
      submit: "Đặt lại mật khẩu",
      submitPending: "Đang đặt lại…",
      successHint: "Đã đặt lại mật khẩu. Vui lòng đăng nhập với mật khẩu mới.",
      goToLogin: "Đăng nhập",
      // Hiển thị khi URL không có token (user mở /?reset= rỗng) — defensive.
      missingTokenTitle: "Link không hợp lệ",
      missingTokenDetail:
        "URL không có token đặt lại. Yêu cầu lại link đặt lại mật khẩu.",
    },
    header: {
      /** @param {string} email */
      hello: (email) => `Xin chào, ${email}`,
      logout: "Đăng xuất",
      adminBadge: "Admin",
      verifyEmailButton: "Xác thực email",
      verifiedBadge: "Đã xác thực email",
      avatarLoggedIn: "Tài khoản",
      avatarLoggedOut: "Đăng nhập / đăng ký",
      modalClose: "Đóng",
    },
    verifyEmail: {
      modalTitle: "Xác thực email",
      modalSubtitle:
        "Bạn cần xác thực email để đóng góp dữ liệu cho cộng đồng. Link xác thực sẽ được gửi đến địa chỉ email bên dưới.",
      emailLabel: "Email",
      submit: "Gửi link xác thực",
      submitPending: "Đang gửi…",
      successHint:
        "Đã gửi link xác thực — kiểm tra hộp thư (và spam). Link hết hạn sau 60 phút.",
      // Confirm page (sau khi user click link trong email)
      confirmTitle: "Xác thực email",
      confirmPending: "Đang xác thực…",
      confirmSuccess:
        "Đã xác thực email thành công! Bạn có thể quay về trang chủ và tiếp tục.",
      confirmGoHome: "Về trang chủ",
      missingTokenTitle: "Link không hợp lệ",
      missingTokenDetail:
        "URL không có token xác thực. Yêu cầu lại link xác thực từ Tài khoản → Xác thực email.",
      requestNewLink: "Gửi link xác thực mới",
    },
    errors: {
      errorCodeLabel: "Mã lỗi",
      /** @param {string} code */
      byCode: (code) => {
        switch (code) {
          case "email_not_verified":
            return "Bạn cần xác thực email trước khi đóng góp cho cộng đồng. Mở Tài khoản → Xác thực email.";
          case "email_verification_invalid":
            return "Link xác thực không hợp lệ. Yêu cầu link mới.";
          case "email_verification_expired":
            return "Link xác thực đã hết hạn. Yêu cầu link mới.";
          case "email_verification_used":
            return "Link xác thực đã được sử dụng.";
          default:
            return "";
        }
      },
    },
  },

  admin: {
    page: {
      title: "Quản trị hệ thống",
      subtitle:
        "Quản lý người dùng, theo dõi thống kê tổng hợp, và chạy đồng bộ toàn hệ thống.",
      statsHeading: "Thống kê",
      usersHeading: "Người dùng",
      reviewHeading: "Duyệt đóng góp cộng đồng",
      syncHeading: "Đồng bộ toàn cục",
      rebuildHeading: "Bản đồ ước lượng",
      gatewaysHeading: "Quản lý gateway",
      trainingHeading: "Dữ liệu đã duyệt",
      retrainHeading: "Mô hình ML",
      notificationsHeading: "Thông báo",
      sidebar: {
        stats: "Tổng quan",
        review: "Phê duyệt",
        training: "Dữ liệu đã duyệt",
        users: "Người dùng",
        gateways: "Gateway",
        sync: "Đồng bộ nguồn",
        rebuild: "Bản đồ ước lượng",
        retrain: "Mô hình ML",
        notifications: "Thông báo",
      },
    },
    stats: {
      loading: "Đang tải thống kê…",
      userCount: "Tổng user",
      onlineUserCount: "User online",
      activeSourceCount: "Đang đóng góp",
      gatewayCount: "Gateway",
      measurementCount: "Điểm đo (training)",
      pendingReviewCount: "Chờ duyệt",
    },
    dashboard: {
      sectionTitle: "Dashboard biểu đồ",
      sectionSubtitle:
        "Mỗi chart có dropdown chọn bucket riêng (tuần/tháng/năm).",
      bucketWeek: "Theo tuần (12 tuần)",
      bucketMonth: "Theo tháng (12 tháng)",
      bucketYear: "Theo năm (5 năm)",
      chartVisitsTitle: "Lượt truy cập website",
      chartSignupsTitle: "User tạo tài khoản mới",
      chartTrainingTitle: "Điểm đo vào bản đồ chung",
      chartTopGwTitle: "Top 5 gateway có nhiều điểm đo nhất",
      loading: "Đang tải dữ liệu…",
      errorLoad: "Không tải được dữ liệu chart.",
      empty: "Chưa có dữ liệu.",
      yAxisCount: "Số lượng",
      gatewayLabel: "Gateway",
    },
    review: {
      loading: "Đang tải hàng chờ duyệt…",
      empty: "Không có đóng góp nào đang chờ duyệt.",
      errorLoad: "Không tải được danh sách chờ duyệt.",
      headers: [
        "Thời điểm",
        "Người gửi",
        "Vị trí",
        "SF",
        "RSSI",
        "SNR",
        "Gateway",
        "Nguồn",
        "",
      ],
      previewTitle: "Xem trước trên bản đồ",
      previewHint:
        "Điểm này sẽ xuất hiện trên bản đồ cộng đồng tại vị trí dưới đây nếu được duyệt.",
      closePreview: "Đóng",
      btnPreview: "Xem",
      btnApprove: "Duyệt",
      btnReject: "Từ chối",
      btnPending: "Đang xử lý…",
      noteLabel: "Lý do từ chối (tuỳ chọn)",
      notePlaceholder: "vd. Toạ độ không khớp gateway, RSSI bất thường…",
      confirm: {
        title: "Xác nhận thao tác",
        approve: "Duyệt đóng góp này lên bản đồ cộng đồng?",
        reject: "Từ chối đóng góp này? Sẽ không hiển thị trên bản đồ cộng đồng.",
        cancel: "Huỷ",
      },
      /** @param {number} total */
      total: (total) => `${total.toLocaleString("vi-VN")} đóng góp đang chờ duyệt`,
      sourceCsv: "CSV upload",
      sourceWebhook: "Webhook",
      sourceUnknown: "Khác",
      batch: {
        heading: "Các file CSV chờ duyệt",
        empty: "Không có file CSV nào đang chờ duyệt.",
        errorLoad: "Không tải được danh sách file chờ duyệt.",
        headers: [
          "Người gửi",
          "Upload lúc",
          "Số điểm chờ",
          "Khoảng thời gian đo",
          "",
        ],
        /** @param {number} pending @param {number} total */
        countLabel: (pending, total) =>
          `${pending}/${total} điểm chờ duyệt`,
        btnViewRows: "Xem chi tiết",
        btnApproveBatch: "Duyệt cả file",
        btnRejectBatch: "Từ chối cả file",
        btnBack: "← Quay lại danh sách file",
        /** @param {number} n */
        mapHeading: (n) =>
          `Bản đồ ${n} điểm đang chờ duyệt trong file này`,
        mapHint:
          "Click vào marker để xem chi tiết 1 điểm. Màu sắc theo RSSI (xanh = mạnh, đỏ = rất yếu).",
        mapLegend: {
          strong: "≥ -100 dBm",
          medium: "-100 đến -115",
          weak: "-115 đến -120",
          veryWeak: "< -120",
        },
        mapNoPoints: "Batch này không còn điểm nào chờ duyệt.",
        confirm: {
          /** @param {number} n */
          approve: (n) =>
            `Duyệt cả file CSV này lên bản đồ cộng đồng (${n} điểm)? Người đóng góp sẽ nhận email cảm ơn.`,
          /** @param {number} n */
          reject: (n) =>
            `Từ chối toàn bộ file CSV này (${n} điểm)? Các điểm sẽ giữ trong quarantine, không lên bản đồ.`,
        },
        /** @param {number} n */
        approvedToast: (n) => `Đã duyệt ${n} điểm trong file.`,
        /** @param {number} n */
        rejectedToast: (n) => `Đã từ chối ${n} điểm trong file.`,
      },
    },
    users: {
      loading: "Đang tải danh sách người dùng…",
      empty: "Chưa có người dùng nào.",
      errorLoad: "Không tải được danh sách người dùng.",
      searchPlaceholder: "Tìm theo email…",
      searchEmpty: "Không có user nào khớp với từ khoá.",
      headers: ["Email", "Đóng góp", "Vai trò", "Trạng thái", "Ngày tạo", ""],
      selfBadge: "Bạn",
      adminBadge: "Admin",
      activeBadge: "Hoạt động",
      disabledBadge: "Đã khoá",
      btnPromote: "Cấp admin",
      btnDemote: "Bỏ admin",
      btnDisable: "Khoá",
      btnEnable: "Mở khoá",
      btnDelete: "Xoá",
      actionsSelfNote: "Không thể tự sửa",
      confirm: {
        title: "Xác nhận thao tác",
        /** @param {string} email */
        disable: (email) =>
          `Khoá tài khoản ${email}? Toàn bộ dữ liệu đóng góp sẽ bị ẩn khỏi bản đồ (KHÔNG xoá — có thể mở khoá để khôi phục).`,
        /** @param {string} email */
        enable: (email) => `Mở khoá tài khoản ${email}? Dữ liệu sẽ hiển thị lại trên bản đồ.`,
        /** @param {string} email */
        promote: (email) =>
          `Cấp quyền admin cho ${email}? User này sẽ truy cập được tab Quản trị.`,
        /** @param {string} email */
        demote: (email) => `Thu hồi quyền admin của ${email}?`,
        /** @param {string} email */
        delete: (email) =>
          `XOÁ VĨNH VIỄN tài khoản ${email}? Mọi token đăng nhập, link nguồn sẽ bị xoá. Dữ liệu đóng góp trên bản đồ cộng đồng GIỮ NGUYÊN nhưng mất liên kết tới user. Thao tác KHÔNG thể hoàn tác.`,
        cancel: "Huỷ",
        pending: "Đang xử lý…",
        errorGeneric: "Thao tác thất bại.",
      },
    },
    sync: {
      title: "Đồng bộ tất cả nguồn",
      subtitle: "Pull data từ mọi linked source đang đóng góp (status=active).",
      btn: "Chạy đồng bộ",
      btnPending: "Đang đồng bộ…",
      /** @param {number} total @param {number} ok @param {number} fail */
      summary: (total, ok, fail) =>
        `Đã xử lý ${total} nguồn — ${ok} thành công, ${fail} lỗi.`,
      /** @param {number} n */
      failuresTitle: (n) => `Chi tiết ${n} nguồn lỗi`,
      errorRequest: "Yêu cầu đồng bộ thất bại.",
    },
    rebuild: {
      title: "Rebuild bản đồ ước lượng",
      subtitle:
        "Chạy lại composite + per-gateway map. Config: P.1812 (lý thuyết) + DTM (địa hình) + per-gateway noise floor + survey overlay per-gw (gateway có điểm đo nhận overlay riêng, gateway không có điểm đo giữ pure physics). KHÔNG dùng Stage 2 ML. Grid 50m × 50m. Chỉ rebuild khi có gói tin mới.",
      btn: "Rebuild ngay",
      btnPending: "Đang chạy…",
      statusQueued: "Đang chờ worker",
      statusRunning: "Đang chạy",
      statusSucceeded: "Hoàn tất",
      statusFailed: "Thất bại",
      /** @param {number} rebuilt @param {number} skipped */
      summary: (rebuilt, skipped) =>
        `${rebuilt} gateway rebuilt, ${skipped} gateway skipped (no new data).`,
      noNewData:
        "Không gateway nào có gói tin mới — toàn bộ skipped, map giữ nguyên.",
      historyHeading: "Lịch sử rebuild",
      historyEmpty: "Chưa có lần rebuild nào.",
      historyHeaders: ["Thời điểm", "Hoàn thành", "Trạng thái", "Rebuilt", "Skipped", "Lỗi"],
      perGwHeading: "Chi tiết theo gateway",
      perGwHeaders: ["Gateway", "Trạng thái", "Ghi chú"],
      perGwStatus: {
        rebuilt: "Đã rebuild",
        pending: "Đang chờ",
        skipped: "Skipped",
        failed: "Lỗi",
      },
      perGwReason: {
        no_data: "Chưa có điểm đo",
        no_new_data: "Không có gói tin mới",
      },
      errorRequest: "Không tạo được job rebuild.",
    },
    training: {
      title: "Dữ liệu đã duyệt vào bản đồ",
      subtitle:
        "Truy vết các batch đã được duyệt vào ts.survey_training. Xoá 1 batch để rút lại quyết định duyệt — sau đó cần rebuild bản đồ + retrain mô hình để ảnh hưởng lan ra.",
      loading: "Đang tải danh sách batch…",
      empty:
        "Chưa có batch nào trong training (hoặc toàn bộ là legacy seed/sync data trước 2026-06-11).",
      errorLoad: "Không tải được danh sách batch.",
      headers: [
        "Người gửi",
        "Vai trò",
        "Loại",
        "Tên file / nguồn",
        "Upload lúc",
        "Số điểm",
        "Duyệt lần cuối",
        "",
      ],
      btnDelete: "Xoá khỏi training",
      btnPending: "Đang xoá…",
      kindLabel: {
        csv: "CSV",
        json: "JSON",
        sync_lpwanmapper: "LPWAN Mapper",
        sync_chirpstack: "ChirpStack",
        live_session: "Chuyến khảo sát",
      },
      kindUnknown: "Không rõ",
      roleLabel: {
        super_admin: "Super admin",
        admin: "Admin",
        user: "Người dùng",
      },
      legacyHint:
        "Batch legacy (trước 2026-06-11) không trace được — đã ẩn khỏi danh sách.",
      confirm: {
        title: "Xác nhận xoá batch khỏi training",
        /** @param {string} who @param {number} n */
        message: (who, n) =>
          `Xoá ${n} điểm đã duyệt của batch (${who}) khỏi ts.survey_training? Quarantine giữ nguyên — không thể undo trừ khi admin duyệt lại.`,
        cancel: "Huỷ",
        confirm: "Xoá",
      },
      /** @param {number} n */
      deletedToast: (n) => `Đã xoá ${n} điểm khỏi training.`,
      followUp: {
        title: "Tiếp tục với Rebuild + Retrain?",
        /** @param {number} n */
        message: (n) =>
          `Đã xoá ${n} điểm khỏi training. Để bản đồ ước lượng + dự đoán ML phản ánh thay đổi này, bạn nên chạy lại cả 2 job (mỗi job độc lập, có thể chạy ngay).`,
        runBoth: "Chạy Rebuild + Retrain",
        runRebuildOnly: "Chỉ chạy Rebuild",
        runRetrainOnly: "Chỉ chạy Retrain",
        skip: "Để sau",
        enqueuedToast: "Đã enqueue job. Mở tab tương ứng để theo dõi tiến độ.",
      },
      errorDelete: "Xoá thất bại.",
    },
    retrain: {
      title: "Retrain mô hình ML",
      subtitle:
        "Train lại Extra Trees Regressor cho /coverage/predict. Sau khi xong, ml-service hot-reload joblib (không cần restart container). Mỗi lần train ~vài phút, tuỳ kích thước dataset.",
      btn: "Retrain ngay",
      btnPending: "Đang chạy…",
      statusQueued: "Đang chờ worker",
      statusRunning: "Đang chạy",
      statusSucceeded: "Hoàn tất",
      statusFailed: "Thất bại",
      /** @param {number|null} rows */
      summary: (rows) =>
        rows == null
          ? "Train xong (chưa đọc được metrics)."
          : `Train xong trên ${rows.toLocaleString("vi-VN")} điểm đo.`,
      metricsHeading: "Metrics",
      metricsLabel: {
        rmse: "RMSE",
        mae: "MAE",
        r2: "R²",
        feature_count: "Số feature",
        ml_service_reload: "Hot-reload ml-service",
      },
      artifactLabel: "Artifact",
      historyHeading: "Toàn bộ lịch sử retrain",
      historyEmpty: "Chưa có lần retrain nào.",
      historyHeaders: ["Thời điểm train", "Thời điểm hoàn thành", "Trạng thái", "Số điểm", "RMSE", "Báo cáo", "Lỗi"],
      reportHeading: "Báo cáo",
      reportView: "Xem",
      reportDownloadPdf: "Tải PDF",
      reportEmpty: "—",
      reportOpenFailed: "Không mở được báo cáo.",
      reportDownloadFailed: "Không tải được PDF.",
      errorRequest: "Không tạo được job retrain.",
      
    },
    notifications: {
      title: "Nhắc rebuild & retrain",
      subtitle:
        "Khi số điểm đo mới (đã duyệt vào ts.survey_training) vượt ngưỡng kể từ lần chạy thành công gần nhất, hệ thống sẽ nhắc admin chạy lại để bản đồ và mô hình ML phản ánh dữ liệu mới.",
      loading: "Đang tải trạng thái dữ liệu…",
      errorLoad: "Không tải được trạng thái dữ liệu.",
      rebuildCardTitle: "Bản đồ ước lượng",
      retrainCardTitle: "Mô hình ML",
      /** @param {number} n @param {number} threshold */
      newPoints: (n, threshold) =>
        `Có ${n.toLocaleString("vi-VN")} điểm đo mới (ngưỡng ${threshold}).`,
      lastRunNever: "Chưa chạy lần nào.",
      /** @param {string} iso */
      lastRunAt: (iso) => `Lần chạy thành công gần nhất: ${new Date(iso).toLocaleString("vi-VN")}.`,
      okMessage: "Dữ liệu mới chưa vượt ngưỡng — chưa cần chạy lại.",
      warnMessage:
        "Đã vượt ngưỡng. Nên chạy lại để cập nhật bản đồ / mô hình theo dữ liệu mới nhất.",
      btnRebuild: "Rebuild ngay",
      btnRetrain: "Retrain ngay",
      btnPending: "Đang enqueue…",
      enqueuedToast: "Đã enqueue job — mở tab tương ứng để theo dõi tiến độ.",
      errorEnqueue: "Không tạo được job.",
    },
    errors: {
      errorCodeLabel: "Mã lỗi",
      statsLoad: "Không tải được thống kê.",
      reviewActionFailed: "Thao tác duyệt thất bại.",
      reviewGone: "Đóng góp này đã được xử lý hoặc không tồn tại.",
      /** @param {string} code */
      byCode: (code) => {
        switch (code) {
          case "admin_required":
            return "Bạn không có quyền admin.";
          case "admin_self_modification":
            return "Không thể tự sửa tài khoản đang đăng nhập.";
          case "user_not_found":
            return "Người dùng không tồn tại.";
          case "invalid_credentials":
            return "Phiên đăng nhập đã hết hạn.";
          default:
            return "";
        }
      },
    },
  },

  sources: {
    page: {
      title: "Dữ liệu của tôi",
      subtitle:
        "Quản lý nguồn dữ liệu liên kết và các file đã đóng góp.",
      empty: "Chưa liên kết nguồn nào. Vào mục \"Thêm nguồn mới\" bên trái.",
      loading: "Đang tải danh sách…",
      errorLoad: "Không tải được danh sách nguồn.",
    },
    sidebar: {
      sectionLabel: "Mục",
      overview: "Tổng quan",
      addSource: "Thêm nguồn mới",
      linkedSources: "Nguồn đã liên kết",
      uploadFile: "Tải lên CSV/JSON",
      dataManagement: "Quản lý dữ liệu",
      uploadHistory: "Lịch sử upload",
    },
    overview: {
      title: "Tổng quan",
      subtitle: "Tóm tắt nguồn dữ liệu và batch đã tải lên.",
      loading: "Đang tải…",
      /** @param {number} n */
      linkedCount: (n) => `${n} nguồn đã liên kết`,
      linkedEmpty: "Chưa liên kết nguồn nào.",
      dataHeading: "Dữ liệu đã tải lên",
      dataEmpty: "Chưa có dữ liệu nào.",
      /** @param {number} batches @param {number} points */
      dataSummary: (batches, points) =>
        `${batches} batch · ${points} điểm`,
      /** @param {number} pub @param {number} pend @param {number} priv */
      dataBreakdown: (pub, pend, priv) =>
        `${pub} công khai · ${pend} chờ duyệt · ${priv} riêng tư`,
    },
    sections: {
      addTitle: "Thêm nguồn mới",
      addSubtitle:
        "Liên kết tài khoản bên ngoài (lpwanmapper, ChirpStack) để pull dữ liệu định kỳ.",
      linkedTitle: "Nguồn đã liên kết",
      linkedSubtitle: "Các nguồn đang đồng bộ về tài khoản của bạn.",
      uploadTitle: "Tải lên CSV/JSON",
      uploadSubtitle:
        "Tải file CSV hoặc JSON chứa phép đo LoRa. Mặc định riêng tư; muốn đóng góp cộng đồng → vào mục \"Quản lý dữ liệu\".",
      manageTitle: "Quản lý dữ liệu",
      manageSubtitle:
        "Các batch còn sống. Bấm \"Đóng góp\" để đưa 1 batch vào bản đồ chung, hoặc \"Xoá\" để gỡ khỏi tài khoản.",
      historyTitle: "Lịch sử upload",
      historySubtitle:
        "Log mọi lần upload / sync (bao gồm batch đã xoá). Chỉ xem.",
    },
    addForm: {
      title: "Thêm nguồn dữ liệu",
      subtitle:
        "Credential dùng để pull dữ liệu định kỳ. Được mã hoá trước khi lưu.",
      sourceTypeLabel: "Loại nguồn",
      labelLabel: "Nhãn (gợi nhớ)",
      labelPlaceholder: "vd. Tài khoản cá nhân",
      submit: "Liên kết",
      submitPending: "Đang xác thực…",
      successHint:
        "Đã liên kết. Mỗi lần \"Tải dữ liệu mới nhất\" tạo 1 batch riêng tư; vào mục \"Quản lý dữ liệu\" để bấm \"Đóng góp\" từng batch.",
      lpwanmapper: {
        emailLabel: "Email lpwanmapper",
        passwordLabel: "Mật khẩu lpwanmapper",
      },
      chirpstack: {
        apiUrlLabel: "API URL",
        apiUrlPlaceholder: "https://chirpstack.example.com:8080",
        apiTokenLabel: "API Token",
        apiTokenHint: "Tạo trong ChirpStack UI → API keys.",
        tenantIdLabel: "Tenant ID (tuỳ chọn)",
        tenantIdHint: "Để trống nếu API key đã scope sẵn theo tenant.",
        skipSslLabel: "Bỏ qua xác minh SSL",
        skipSslHint:
          "Chỉ tick nếu server thiếu intermediate cert hoặc dùng self-signed. KHÔNG dùng cho production.",
      },
    },
    card: {
      statusActive: "Đang đồng bộ dữ liệu",
      statusPaused: "Tạm dừng đồng bộ dữ liệu",
      statusFailed: "Lỗi khi đồng bộ dữ liệu",
      lastSyncNever: "Chưa đồng bộ dữ liệu lần nào",
      /** @param {string} when */
      lastSyncAt: (when) => `Sync gần nhất: ${when}`,
      lastSyncError: "Lỗi sync gần nhất:",
      btnPause: "Tạm dừng",
      btnResume: "Bật đồng bộ dữ liệu",
      btnSyncNow: "Tải dữ liệu mới nhất",
      btnSyncPending: "Đang tải dữ liệu…",
      btnSyncDisabledPaused:
        "Nguồn đang tạm dừng. Nhấn \"Bật đồng bộ dữ liệu\" trước khi tải dữ liệu mới.",
      btnSyncDisabledFailed:
        "Nguồn đang ở trạng thái lỗi. Khắc phục lỗi rồi bật lại đồng bộ.",
      syncConflictTitle: "Không thể tải dữ liệu lúc này",
      /** @param {string} otherLabel @param {string} otherType */
      syncConflictBody: (otherLabel, otherType) =>
        `Nguồn "${otherLabel}" (${otherType}) đang ở trạng thái Đang đồng bộ dữ liệu. ` +
        `Vui lòng vào nguồn "${otherLabel}" bấm "Tạm dừng" trước, rồi mới tải dữ liệu cho nguồn hiện tại.`,
      syncConflictDismiss: "Đã hiểu",
      btnDelete: "Xoá liên kết",
      btnRotateWebhook: "Tạo lại webhook URL",
      btnRotateWebhookPending: "Đang tạo…",
      btnShowDevices: "Xem thiết bị",
      btnHideDevices: "Ẩn thiết bị",
      confirmDelete:
        "Xoá liên kết sẽ ngừng pull dữ liệu mới. Dữ liệu đã đóng góp vẫn giữ nguyên trên bản đồ. Tiếp tục?",
      confirmRotateWebhook:
        "Tạo webhook URL mới sẽ vô hiệu hoá URL hiện tại NGAY LẬP TỨC — ChirpStack sẽ bị 401 cho tới khi bạn cập nhật URL mới. Tiếp tục?",
      /** @param {number} g @param {number} m @param {number} d */
      syncOk: (g, m, d) =>
        `Sync xong: ${g} gateway, ${d} thiết bị, ${m} điểm đo mới.`,
    },

    webhookSetup: {
      title: "Webhook ChirpStack — copy ngay",
      subtitle:
        "Đây là URL+token DUY NHẤT để ChirpStack đẩy uplink về tài khoản của bạn. Token chỉ hiển thị 1 LẦN — copy ngay; muốn xem lại phải tạo lại (token cũ sẽ bị vô hiệu).",
      urlLabel: "Webhook URL",
      tokenLabel: "Webhook token",
      copyBtn: "Sao chép URL",
      copyDone: "Đã copy!",
      dismissBtn: "Đã copy xong",
      stepsTitle: "Hướng dẫn 4 bước trong ChirpStack",
      steps: [
        "Mở ChirpStack UI → chọn Application chứa device của bạn.",
        "Vào tab Integrations → Add → HTTP.",
        "Dán URL ở trên vào ô \"Endpoint URL (uplink)\". Encoding: JSON.",
        "Lưu lại. Mỗi uplink sẽ tự đẩy về web-app với đúng provenance của bạn.",
      ],
    },

    devices: {
      heading: "Thiết bị đã tải lên",
      loading: "Đang tải thiết bị…",
      empty: "Chưa có thiết bị nào. Bấm \"Sync ngay\" để kéo từ provider.",
      errorLoad: "Không tải được danh sách thiết bị.",
      headers: ["DevEUI", "Tên", "Last seen"],
      lastSeenNever: "—",
      /** @param {number} n */
      total: (n) => `${n} thiết bị`,
    },
    errors: {
      errorCodeLabel: "Mã lỗi",
      /** @param {string} code */
      byCode: (code) => {
        switch (code) {
          case "credential_test_failed":
            return "Credential không hợp lệ — kiểm tra lại thông tin đăng nhập / API token.";
          case "credential_already_linked":
            return "Tài khoản này đã được người dùng khác liên kết. Mỗi tài khoản bên ngoài chỉ được liên kết bởi 1 người.";
          case "conflicting_source_type":
            return "Pause nguồn cũ trước khi liên kết nguồn mới để tránh dữ liệu trùng.";
          case "linked_source_not_found":
            return "Nguồn không tồn tại hoặc đã bị xoá.";
          case "linking_error":
            return "Yêu cầu không hợp lệ.";
          case "webhook_auth_failed":
            return "Webhook token không hợp lệ hoặc đã bị thu hồi.";
          default:
            return "";
        }
      },
    },
  },

  contributeUpload: {
    tabLabel: "Đóng góp dữ liệu",
    title: "Tải lên dữ liệu khảo sát",
    description:
      "Tải file CSV hoặc JSON chứa các phép đo LoRa của bạn. Mọi file mặc định riêng tư — vào mục \"Quản lý dữ liệu\" để bấm \"Đóng góp\" từng batch sau khi xem lại.",
    fields: {
      file: "File CSV hoặc JSON",
    },
    checklist: {
      title: "Checklist trước khi đóng góp",
      items: [
        "Có đủ latitude, longitude (toạ độ WGS84).",
        "Vị trí nằm trong lãnh thổ Việt Nam.",
        "gateway_code đã được liên kết với tài khoản (xem tab Nguồn dữ liệu).",
        "Tài khoản nên đã xác minh email — ngưỡng vật lý sẽ lỏng hơn.",
      ],
    },
    submit: "Tải lên",
    submitPending: "Đang xử lý…",
    reset: "Chọn lại file",
    csvHint:
      "CSV/JSON: cột bắt buộc timestamp, latitude, longitude, rssi_dbm, spreading_factor, gateway_code — hệ thống tự nhận diện synonym (vd RSSI, lat, lng, sf, gateway_id…), không phụ thuộc thứ tự cột, cột thừa bị bỏ qua. Tuỳ chọn: snr_db (mặc định 0), frequency_mhz (mặc định 923), device_id. JSON: hỗ trợ (A) mảng object cùng schema, hoặc (C) webhook TTN v3 / ChirpStack v4 — 1 event tự động bung thành N row theo số gateway. Tối đa 1000 dòng/file.",
    fileSelected: (/** @type {string} */ name, /** @type {number} */ size) =>
      `Đã chọn: ${name} (${(size / 1024).toFixed(1)} KB)`,
    noFileSelected: "Chưa chọn file.",
    summary: {
      title: "Kết quả",
      parsed: (/** @type {number} */ n) => `${n} dòng đọc được`,
      parseRejected: (/** @type {number} */ n) => `${n} dòng bị loại khi đọc`,
      inserted: (/** @type {number} */ n) => `${n} dòng đã ghi vào quarantine`,
      promoted: (/** @type {number} */ n) => `${n} dòng đã được duyệt vào bộ cộng đồng`,
      promoteRejected: (/** @type {number} */ n) => `${n} dòng không qua kiểm định`,
    },
    parseErrorTitle: "Một số dòng không hợp lệ:",
    rejectReasons: {
      title: "Lý do bị kiểm định loại:",
      /** @param {string} reason @param {number} count */
      row: (reason, count) => `${reason}: ${count} dòng`,
    },
    rejectReasonLabel: {
      out_of_region: "Toạ độ ngoài Việt Nam",
      unknown_gateway: "Gateway không có trong hệ thống",
      physics_outlier: "RSSI lệch quá xa so với dự đoán ITU",
      physics_unavailable: "Không tính được dự đoán ITU (DEM không phủ điểm)",
      unknown: "Không xác định",
    },
    errors: {
      title: "Lỗi tải lên",
      fileEmpty: "Vui lòng chọn 1 file CSV hoặc JSON.",
      fileTooLarge: "File vượt 1 MB. Hãy chia nhỏ.",
    },
    samplePrompt: "Cần file mẫu? Xem cấu trúc cột ở phần \"CSV hint\" bên trên.",
  },

  // Bảng "Quản lý dữ liệu" — batch đang sống (chưa xoá). Mỗi row 1 lần upload
  // CSV/JSON hoặc 1 lần sync linked source. Có 2 nút hành động: Đóng góp + Xoá.
  dataManagementTable: {
    title: "Quản lý dữ liệu",
    subtitle:
      "Danh sách file bạn đã tải lên hoặc các đợt đồng bộ từ nguồn liên kết. " +
      "Bấm \"Đóng góp\" để gửi 1 batch vào bản đồ chung.",
    loading: "Đang tải…",
    empty: "Chưa có dữ liệu nào. Vào mục \"Tải lên CSV/JSON\" hoặc \"Nguồn đã liên kết\".",
    errorLoad: "Không tải được danh sách dữ liệu.",
    headers: [
      "Thời điểm upload",
      "Tên file",
      "Số điểm",
      "Loại",
      "Trạng thái",
      "",
    ],
    btnContribute: "Đóng góp",
    btnContributePending: "Đang gửi…",
    btnDelete: "Xoá",
    btnDeletePending: "Đang xoá…",
    confirmDelete: (/** @type {number} */ n) =>
      `Xoá batch này (${n} điểm)? Không thể hoàn tác.`,
    successTitle: "Đã gửi đóng góp",
    successLine: (/** @type {number} */ queued) =>
      `${queued} điểm đã chuyển sang chờ admin duyệt.`,
    errorTitle: "Không gửi được đóng góp",
    deleteErrorTitle: "Không xoá được batch",
  },

  // Bảng "Lịch sử upload" — read-only log mọi batch (kể cả deleted).
  uploadHistoryTable: {
    title: "Lịch sử upload",
    subtitle:
      "Log mọi lần upload / sync — bao gồm các batch đã xoá. Read-only.",
    loading: "Đang tải…",
    empty: "Chưa có lịch sử nào.",
    errorLoad: "Không tải được lịch sử upload.",
    headers: [
      "Thời điểm",
      "Tên file",
      "Số điểm",
      "Loại",
      "Trạng thái",
    ],
  },

  // Nhãn loại upload — dùng chung 2 bảng trên.
  uploadKindLabel: {
    csv: "CSV",
    json: "JSON",
    sync_lpwanmapper: "Đồng bộ Lpwanmapper",
    sync_chirpstack: "Đồng bộ ChirpStack",
    live_session: "Chuyến khảo sát",
  },

  // Nhãn trạng thái batch — dùng chung 2 bảng trên.
  batchStatusLabel: {
    private: "Riêng tư",
    pending: "Chờ duyệt",
    public: "Công khai",
    rejected: "Bị từ chối",
    deleted: "Đã xoá",
  },

};
