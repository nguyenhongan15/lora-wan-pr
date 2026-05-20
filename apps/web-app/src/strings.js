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
      gatewayAddress: "Địa chỉ",
      gatewayAddressLoading: "Đang tải địa chỉ…",
      gatewayAddressError: "Không lấy được địa chỉ",
      searchStatus: "Trạng thái",
      // Sai số (1σ ~68% CI) + Độ chính xác (95% CI ~1.96σ) — tính từ σ²
      // shadow fading của môi trường (urban σ=8, suburban σ=6, rural σ=4).
      errorMargin: {
        label: "Sai số",
        /** @param {number} sigmaDb */
        value: (sigmaDb) => `±${sigmaDb.toFixed(1)} dB (1σ)`,
      },
      accuracy: {
        label: "Độ chính xác (95%)",
        /** @param {number} sigmaDb */
        value: (sigmaDb) => `±${(1.96 * sigmaDb).toFixed(1)} dB`,
      },
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
      usedTxPower: {
        label: "Công suất phát",
        /** @param {number} dbm */
        value: (dbm) => `${dbm} dBm`,
      },
      usedEnvironment: {
        label: "Môi trường",
      },
      // Path loss tổng (basic + BEL nếu có). Hữu ích để engineer debug:
      // RSSI thấp vì terrain hay vì building entry loss.
      pathLoss: {
        label: "Suy hao đường truyền",
        /** @param {number} db */
        value: (db) => `${db.toFixed(1)} dB`,
      },
      // Khoảng cách target → serving gateway (gateway có tín hiệu mạnh nhất,
      // chọn theo min(UL_margin, DL_margin), không phải nearest geographic).
      distanceToGateway: {
        label: "Khoảng cách đến gateway",
        /** @param {number} km */
        value: (km) => (km < 1 ? `${(km * 1000).toFixed(0)} m` : `${km.toFixed(2)} km`),
      },
      // Block thông số đường truyền dữ liệu LoRaWAN (bitrate, ToA, max payload)
      // — pure function của SF, BW=125kHz, CR=4/5 (AS923-2 DT=0).
      dataLink: {
        sectionTitle: "Đường truyền dữ liệu",
        bitrate: "Tốc độ",
        timeOnAir: "Thời gian phát 23 B",
        maxPayload: "Payload tối đa",
        /** @param {number} bytes */
        maxPayloadValue: (bytes) => `${bytes} byte`,
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
      // Bottleneck pill ở Layer 1 — siêu ngắn để fit cạnh status badge.
      bottleneckShort: {
        uplink: "Bottleneck: Up Link",
        downlink: "Bottleneck: Down Link",
        both_ok: "Cân bằng 2 chiều",
      },
      // UL/DL mini-table trong Layer 2.
      bidir: {
        sectionTitle: "Dự đoán 2 chiều",
        ul: "UL(device→GW)",
        dl: "DL(GW→device)",
        colDir: "",
        colRssi: "RSSI",
        colSnr: "SNR",
        colMargin: "Margin",
        /** @param {number} db */
        marginValue: (db) => `${db >= 0 ? "+" : ""}${db.toFixed(1)} dB`,
      },
      copyLink: {
        label: "Sao chép liên kết",
        done: "Đã copy!",
      },
    },
    apiError:
      "Không tải được dữ liệu API. Kiểm tra api-service đang chạy chưa (http://localhost:8000/healthz).",
    tileErrorTitle: "Tile không load được",
    sfPicker: {
      label: "SF",
      /** @param {number} sf */
      option: (sf) => `SF${sf}`,
      auto: "Tự động",
    },
    txPowerPicker: {
      label: "Công suất phát",
      hint: "8 mức ADR theo LoRaWAN AS923-2 (TXPower 0..7, bước 2 dB, cap 14 dBm).",
      // LoRaWAN AS923 regional params §2.7.3 — TXPower index 0..7 = Max EIRP
      // trừ 0, 2, 4, ... 14 dB. Với Max EIRP = 14 dBm (cap VN) → 14, 12, ..., 0.
      options: [
        { value: 14, label: "14 dBm (TXPower 0)" },
        { value: 12, label: "12 dBm (TXPower 1)" },
        { value: 10, label: "10 dBm (TXPower 2)" },
        { value: 8, label: "8 dBm (TXPower 3)" },
        { value: 6, label: "6 dBm (TXPower 4)" },
        { value: 4, label: "4 dBm (TXPower 5)" },
        { value: 2, label: "2 dBm (TXPower 6)" },
        { value: 0, label: "0 dBm (TXPower 7)" },
      ],
    },
    environmentPicker: {
      label: "Môi trường",
      hint: "Trong nhà sẽ cộng thêm suy hao xuyên tường theo ITU-R P.2109.",
      options: [
        { value: "outdoor", label: "Ngoài trời", short: "Ngoài trời" },
        { value: "indoor", label: "Trong nhà", short: "Trong nhà" },
        {
          value: "indoor_deep",
          label: "Sâu trong nhà",
          short: "Sâu trong nhà",
        },
      ],
    },
    viewModePicker: {
      title: "Loại bản đồ",
      ariaLabel: "Chọn loại bản đồ",
      modes: {
        points: "Bản đồ điểm đo",
        heatmap: "Bản đồ nhiệt mật độ",
        // Tab "Bản đồ phủ sóng" có 2 layer:
        minsf: "Bản đồ min-SF",
        estimate: "Bản đồ ước lượng",
      },
    },
    minsf: {
      panelTitle: "Bản đồ phủ sóng",
      selector: {
        label: "Chọn gateway",
        placeholder: "— Chọn gateway —",
        loading: "Đang tải gateway…",
        empty: "Chưa có gateway nào.",
      },
      legend: {
        title: "Min-SF",
        /** @param {number} sf */
        sfLabel: (sf) => `SF${sf}`,
        noCoverage: "Không phủ",
        hint: "SF nhỏ = sóng mạnh, đỡ spread. SF lớn = vùng rìa, cần sensitivity cao.",
      },
      loadError:
        "Không tải được dữ liệu phủ sóng. Gateway này có thể chưa được precompute.",
      loadEmpty:
        "Chưa có dữ liệu phủ sóng cho gateway này — chạy lại `precompute_minsf.py`.",
      model: "Mô hình: ITU-R P.1812 + P.2108 (clutter)",
    },
    estimate: {
      panelTitle: "Bản đồ ước lượng",
      placeholder: "Đang phát triển — chưa khả dụng.",
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
      clearAll: "Xoá tất cả điểm dự đoán",
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
    // Bidirectional link budget block
    bidirectional: {
      sectionTitle: "Cân bằng 2 chiều",
      directionUplink: "Lên (device → gateway)",
      directionDownlink: "Xuống (gateway → device)",
      colRssi: "RSSI",
      colSnr: "SNR",
      colMargin: "Margin",
      colStatus: "Trạng thái",
      bottleneckLabel: "Nút thắt",
      bottleneck: {
        uplink: "Chiều LÊN — device TX/anten là điểm yếu.",
        downlink: "Chiều XUỐNG — device RX là điểm yếu.",
        both_ok: "Cân bằng — cả 2 chiều đều khoẻ.",
      },
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
      headers: ["#", "Label", "Địa chỉ / Toạ độ", "Trạng thái", "Nút thắt", "RSSI", "SNR", "SF gợi ý"],
      ok: "OK",
      error: "Lỗi",
    },
    bottleneck: {
      uplink: "Lên",
      downlink: "Xuống",
      both_ok: "Cân bằng",
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
        "Liên kết tài khoản bên ngoài (vd. lpwanmapper, ChirpStack) để đóng góp dữ liệu khảo sát lên bản đồ cộng đồng.",
      empty: "Chưa liên kết nguồn nào. Dùng form bên trên để thêm.",
      loading: "Đang tải danh sách…",
      errorLoad: "Không tải được danh sách nguồn.",
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
        "Đã liên kết. Mặc định CHƯA đóng góp lên cộng đồng — bấm \"Đóng góp\" trong thẻ bên dưới khi sẵn sàng.",
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
      heading: "Thiết bị đã sync",
      loading: "Đang tải thiết bị…",
      empty: "Chưa có thiết bị nào. Bấm \"Sync ngay\" để kéo từ provider.",
      errorLoad: "Không tải được danh sách thiết bị.",
      headers: ["DevEUI", "Tên", "Lần cuối thấy"],
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
};
