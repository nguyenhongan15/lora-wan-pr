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
    title: "LoRa MAP",
    subtitle: "v2 — Đà Nẵng pilot. Stage 1 + 200 survey points.",
    tabs: {
      map: "Bản đồ điểm đo",
      heatmap: "Bản đồ phủ sóng",
      predict: "Dự đoán điểm",
      bulk: "Tra cứu hàng loạt",
      admin: "Gateway list",
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
      gateway: "Gateway",
      strongRssi: "≥ -100",
      mediumRssi: "≥ -110",
      weakRssi: "≥ -120",
      noCoverage: "< -120",
      // Legend dạng dài (component Legend nội bộ — hiện không dùng nhưng giữ
      // chuỗi để khi bật lại không bị mất đồng bộ).
      strongLong: "Mạnh (≥ -100 dBm)",
      goodLong: "Tốt (-100 đến -115)",
      weakLong: "Yếu (-115 đến -120)",
      noCoverageLong: "Không phủ (< -120)",
    },
    popup: {
      surveyTitle: "Survey point",
      rssiLabel: "RSSI",
      snrLabel: "SNR",
      /** @param {number} sf */
      sfLabel: (sf) => `SF${sf}`,
      gatewayTx: "TX",
      gatewayGain: "gain",
      gatewayAntenna: "Antenna",
      gatewayFreq: "Freq",
      searchStatus: "Trạng thái",
      searchConfidence: "Confidence",
      // Header cho popup ở tab "Dự đoán điểm".
      predictTitle: "Điểm dự đoán",
      /** @param {number} lat @param {number} lng */
      coords: (lat, lng) => `${lat.toFixed(5)}, ${lng.toFixed(5)}`,
      // Layer 1 — câu giải thích ngắn cho end-user (per business-logic §4.2).
      layer1Sentence: {
        strong: "Phủ sóng tốt — gateway gần, link ổn định.",
        marginal: "Phủ tạm — link healthy nhưng SNR sát ngưỡng. Vẫn dùng được.",
        weak: "Phủ yếu — gần ngưỡng sensitivity. Nên nâng SF hoặc đặt thêm gateway.",
        no_coverage: "Không phủ — không có gateway trong tầm.",
      },
      // Layer 2 — chi tiết kỹ thuật cho engineer (P1/P2).
      usedSf: {
        label: "SF dùng",
        /** @param {number} sf */
        value: (sf) => `SF${sf}`,
      },
      recommendedSf: {
        label: "SF khuyến nghị",
        /** @param {number} sf */
        value: (sf) => `SF${sf}`,
      },
      sfMismatchHint: "(khác SF dùng)",
      nearestGateway: {
        label: "Gateway phục vụ",
        none: "không xác định",
      },
      toggleLayer2: {
        show: "Xem chi tiết kỹ thuật ▾",
        hide: "Ẩn chi tiết ▴",
      },
    },
    apiError:
      "Không tải được dữ liệu API. Kiểm tra api-service đang chạy chưa (http://localhost:8000/healthz).",
    tileErrorTitle: "Tile không load được",
    sfPicker: {
      label: "SF",
      /** @param {number} sf */
      option: (sf) => `SF${sf}`,
    },
    urlPositionLabel: "Vị trí từ URL",
    predictPanel: {
      title: "Dự đoán điểm",
      hint: "Click lên bản đồ để chọn điểm",
      latLabel: "Vĩ độ",
      lngLabel: "Kinh độ",
      empty: "—",
      submit: "Dự đoán",
      submitting: "Đang dự đoán…",
      error: "Dự đoán thất bại — thử lại.",
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
      rssi: "RSSI",
      snr: "SNR",
      confidence: "Confidence",
      model: "Model",
      recommendedSf: "SF khuyến nghị",
      gateway: "Gateway phục vụ",
    },
    layer1Sentence: {
      strong: "Phủ sóng tốt — gateway gần, link ổn định.",
      marginal:
        "Phủ tạm — link healthy nhưng SNR sát ngưỡng. Vẫn dùng được.",
      weak:
        "Phủ yếu — gần ngưỡng sensitivity. Nên nâng SF hoặc đặt thêm gateway.",
      no_coverage: "Không phủ — không có gateway trong tầm.",
    },
    toggleLayer2: {
      show: "Xem chi tiết kỹ thuật ▾",
      hide: "Ẩn chi tiết ▴",
    },
    gatewayNone: "không xác định",
  },

  adminGateways: {
    title: "Quản lý Gateway",
    addButton: "+ Thêm gateway",
    loading: "Đang tải…",
    listError: "Không tải được danh sách gateway.",
    detailError: "Không tải được dữ liệu gateway.",
    emptyState: "Chưa có gateway. Thêm mới để bắt đầu.",
    tableHeaders: [
      "Code",
      "Name",
      "Lat",
      "Lon",
      "AGL (m)",
      "Gain (dBi)",
      "TX (dBm)",
      "Freq (MHz)",
      "",
    ],
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
    ifMatchLabel: "If-Match",
    modalCloseAria: "Đóng",
  },

  bulkLookup: {
    title: "Tra cứu phủ sóng hàng loạt (CSV)",
    description:
      "Tải lên CSV chứa danh sách địa chỉ hoặc tọa độ. Mỗi dòng trả về 1 kết quả độc lập — 1 lỗi không làm hỏng cả batch.",
    fields: {
      file: "File CSV",
      sf: "Spreading Factor",
      csv: "Hoặc dán CSV trực tiếp",
    },
    csvHint:
      "Cột hợp lệ: label, address, latitude, longitude. Mỗi dòng cần address HOẶC (latitude+longitude).",
    /** @param {number} n */
    previewCount: (n) => `Sẽ tra cứu ${n} dòng (tối đa 500).`,
    submit: "Tra cứu",
    submitPending: "Đang tra cứu…",
    parseErrorTitle: "Parse error:",
    sampleCsv: "Dùng CSV mẫu",
    download: "Tải kết quả CSV",
    summary: {
      /** @param {number} ok @param {number} err */
      counts: (ok, err) => `${ok} thành công · ${err} lỗi`,
    },
    table: {
      headers: ["#", "Label", "Địa chỉ / Toạ độ", "Trạng thái", "RSSI", "SNR", "SF gợi ý"],
      ok: "OK",
      error: "Lỗi",
    },
    parse: {
      headerRequired: "CSV cần ít nhất header + 1 dòng dữ liệu.",
      noColumn: "CSV cần ít nhất 1 cột: address, latitude hoặc longitude.",
      /** @param {number} line @param {number} got @param {number} want */
      colCountMismatch: (line, got, want) =>
        `Dòng ${line}: số cột ${got} ≠ header ${want}`,
      noRecord: "Không có dòng nào hợp lệ.",
      /** @param {number} line @param {string} reason */
      rowError: (line, reason) => `Dòng ${line}: ${reason}`,
    },
  },

};
