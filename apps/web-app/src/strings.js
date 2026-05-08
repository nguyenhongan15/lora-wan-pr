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
      sources: "Nguồn dữ liệu",
      adminPanel: "Quản trị",
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
      strongRssi: "≥ -100 dBm",
      mediumRssi: "-115 đến -100 dBm",
      weakRssi: "-120 đến -115 dBm",
      noCoverage: "< -120 dBm",
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
    filters: {
      contributor: {
        legend: "Hiển thị",
        community: "Cộng đồng",
        me: "Của tôi",
        meLoggedOutHint: "Đăng nhập để xem dữ liệu của riêng bạn.",
        user: "Người dùng cụ thể",
        userIdPlaceholder: "UUID người dùng",
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
      timeRange: {
        legend: "Khoảng thời gian",
        presets: {
          all: "Tất cả",
          "24h": "24 giờ qua",
          "7d": "7 ngày qua",
          "30d": "30 ngày qua",
        },
      },
      sort: {
        legend: "Sắp xếp",
        sortBy: {
          timestamp: "Thời gian",
          rssi: "RSSI",
          snr: "SNR",
        },
        sortOrder: {
          desc: "Mạnh → yếu",
          asc: "Yếu → mạnh",
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
      "STT",
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
    header: {
      /** @param {string} email */
      hello: (email) => `Xin chào, ${email}`,
      logout: "Đăng xuất",
      adminBadge: "Admin",
      avatarLoggedIn: "Tài khoản",
      avatarLoggedOut: "Đăng nhập / đăng ký",
      modalClose: "Đóng",
    },
    errors: {
      errorCodeLabel: "Mã lỗi",
    },
  },

  admin: {
    page: {
      title: "Quản trị hệ thống",
      subtitle:
        "Quản lý người dùng, theo dõi thống kê tổng hợp, và chạy đồng bộ toàn hệ thống.",
      statsHeading: "Thống kê",
      usersHeading: "Người dùng",
      syncHeading: "Đồng bộ toàn cục",
    },
    stats: {
      loading: "Đang tải thống kê…",
      userCount: "Tổng user",
      activeUserCount: "User đang hoạt động",
      linkedSourceCount: "Nguồn đã liên kết",
      activeSourceCount: "Đang đóng góp",
      gatewayCount: "Gateway",
      measurementCount: "Điểm đo (training)",
    },
    users: {
      loading: "Đang tải danh sách người dùng…",
      empty: "Chưa có người dùng nào.",
      errorLoad: "Không tải được danh sách người dùng.",
      headers: ["Email", "Đóng góp", "Vai trò", "Trạng thái", "Ngày tạo", ""],
      selfBadge: "Bạn",
      adminBadge: "Admin",
      activeBadge: "Hoạt động",
      disabledBadge: "Đã khoá",
      btnPromote: "Cấp admin",
      btnDemote: "Bỏ admin",
      btnDisable: "Khoá",
      btnEnable: "Mở khoá",
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
    errors: {
      errorCodeLabel: "Mã lỗi",
      statsLoad: "Không tải được thống kê.",
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
      title: "Nguồn dữ liệu của tôi",
      subtitle:
        "Liên kết tài khoản bên ngoài (vd. lpwanmapper) để đóng góp dữ liệu khảo sát lên bản đồ cộng đồng.",
      empty: "Chưa liên kết nguồn nào. Dùng form bên trên để thêm.",
      loading: "Đang tải danh sách…",
      errorLoad: "Không tải được danh sách nguồn.",
    },
    addForm: {
      title: "Thêm nguồn lpwanmapper",
      subtitle:
        "Credential dùng để pull dữ liệu định kỳ. Mật khẩu được mã hoá trước khi lưu.",
      sourceTypeLabel: "Loại nguồn",
      labelLabel: "Nhãn (gợi nhớ)",
      labelPlaceholder: "vd. Tài khoản cá nhân",
      emailLabel: "Email lpwanmapper",
      passwordLabel: "Mật khẩu lpwanmapper",
      submit: "Liên kết",
      submitPending: "Đang xác thực…",
      successHint:
        "Đã liên kết. Mặc định CHƯA đóng góp lên cộng đồng — bấm \"Đóng góp\" trong thẻ bên dưới khi sẵn sàng.",
    },
    card: {
      statusActive: "Đang sync",
      statusPaused: "Tạm dừng sync",
      statusFailed: "Sync lỗi",
      contributeOn: "Đang đóng góp",
      contributeOff: "Chưa đóng góp",
      lastSyncNever: "Chưa sync lần nào",
      /** @param {string} when */
      lastSyncAt: (when) => `Sync gần nhất: ${when}`,
      lastSyncError: "Lỗi sync gần nhất:",
      btnContributeOn: "Đóng góp cộng đồng",
      btnContributeOff: "Dừng đóng góp",
      btnPause: "Tạm dừng sync",
      btnResume: "Bật sync",
      btnSyncNow: "Sync ngay",
      btnSyncPending: "Đang sync…",
      btnDelete: "Xoá liên kết",
      confirmDelete:
        "Xoá liên kết sẽ ngừng pull dữ liệu mới. Dữ liệu đã đóng góp vẫn giữ nguyên trên bản đồ. Tiếp tục?",
      /** @param {number} g @param {number} m */
      syncOk: (g, m) =>
        `Sync xong: ${g} gateway, ${m} điểm đo mới.`,
    },
    errors: {
      errorCodeLabel: "Mã lỗi",
      /** @param {string} code */
      byCode: (code) => {
        switch (code) {
          case "credential_test_failed":
            return "Email/mật khẩu lpwanmapper không đúng.";
          case "linked_source_not_found":
            return "Nguồn không tồn tại hoặc đã bị xoá.";
          case "linking_error":
            return "Yêu cầu không hợp lệ.";
          default:
            return "";
        }
      },
    },
  },
};
