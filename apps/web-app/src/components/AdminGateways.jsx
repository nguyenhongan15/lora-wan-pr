// @ts-check
import { useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  ApiError,
  createGateway,
  getGateway,
  listGateways,
  patchGateway,
} from "../api/client.js";
import { listPendingGateways } from "../admin/client.js";
import { AlertModal, ConfirmModal } from "./Modal.jsx";
import { strings } from "../strings.js";

const t = strings.adminGateways;

/**
 * @param {{ editable?: boolean }} props
 */
export function AdminGateways({ editable = false }) {
  const [tab, setTab] = useState(
    /** @type {"manage" | "pending" | "create"} */ ("manage"),
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-4 md:px-6 md:py-6">
      <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
        <TabButton
          active={tab === "manage"}
          onClick={() => setTab("manage")}
          label={t.tabs.manage}
        />
        {editable && (
          <TabButton
            active={tab === "pending"}
            onClick={() => setTab("pending")}
            label={t.tabs.pending}
          />
        )}
        {editable && (
          <TabButton
            active={tab === "create"}
            onClick={() => setTab("create")}
            label={t.tabs.create}
          />
        )}
      </div>

      {tab === "manage" && <ManageGatewaysTab editable={editable} />}
      {tab === "pending" && editable && <PendingGatewaysTab />}
      {tab === "create" && editable && <CreateGatewayTab />}
    </div>
  );
}

/**
 * @param {{ active: boolean, onClick: () => void, label: string }} props
 */
function TabButton({ active, onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors " +
        (active
          ? "border-slate-900 text-slate-900"
          : "border-transparent text-slate-500 hover:text-slate-700")
      }
    >
      {label}
    </button>
  );
}

/**
 * @param {{ editable: boolean }} props
 */
function ManageGatewaysTab({ editable }) {
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["gateways", "admin"],
    // includeHidden=true: admin cần thấy gw đã bị ẩn khỏi bản đồ chung để restore.
    queryFn: () => listGateways(undefined, { includeHidden: true }),
  });

  const [editing, setEditing] = useState(
    /** @type {string | null} */ (null),
  );

  // Visibility toggle: ConfirmModal cần biết gateway hiện tại + chiều đổi.
  const [visTarget, setVisTarget] = useState(
    /** @type {{ id: string, code: string, makePublic: boolean } | null} */ (null),
  );
  const [visError, setVisError] = useState(/** @type {string | null} */ (null));

  const visMutation = useMutation({
    /** @param {{ id: string, makePublic: boolean }} args */
    mutationFn: async ({ id, makePublic }) => {
      // patchGateway cần ETag — fetch fresh detail trước khi PATCH.
      const detail = await getGateway(id);
      if (!detail.etag) throw new Error("missing etag");
      return patchGateway(id, detail.etag, { is_public: makePublic });
    },
    onSuccess: () => {
      setVisTarget(null);
      setVisError(null);
      qc.invalidateQueries({ queryKey: ["gateways"] });
    },
    onError: () => {
      setVisError(t.visibilityError);
    },
  });

  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{t.title}</h2>
      </div>

      {listQ.isLoading && (
        <div className="text-sm text-slate-500">{t.loading}</div>
      )}
      {listQ.isError && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {t.listError}
        </div>
      )}

      {listQ.data && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                {t.tableHeaders
                  .filter((_, i) => editable || i < t.tableHeaders.length - 1)
                  .map((h, i) => (
                    <th
                      key={h || `col-${i}`}
                      className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-slate-500"
                    >
                      {h}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {listQ.data.items.map((g, i) => (
                <tr key={g.id}>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2 font-mono text-xs">{g.code}</td>
                  <td className="px-3 py-2">{g.name}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {g.latitude.toFixed(4)}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {g.longitude.toFixed(4)}
                  </td>
                  <td className="px-3 py-2">{g.antenna_height_m}</td>
                  <td className="px-3 py-2">{g.antenna_gain_dbi}</td>
                  <td className="px-3 py-2">{g.tx_power_dbm}</td>
                  <td className="px-3 py-2">{g.frequency_mhz}</td>
                  <td className="px-3 py-2">
                    <StateBadge state={g.state} lastSeenAt={g.last_seen_at ?? null} />
                    {g.is_public === false && (
                      <span className="ml-2 inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
                        {t.hiddenBadge}
                      </span>
                    )}
                  </td>
                  {editable && (
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => setEditing(g.id)}
                          className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
                        >
                          {t.editButton}
                        </button>
                        <button
                          onClick={() =>
                            setVisTarget({
                              id: g.id,
                              code: g.code,
                              makePublic: g.is_public === false,
                            })
                          }
                          className={
                            "rounded-md border px-2 py-1 text-xs " +
                            (g.is_public === false
                              ? "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                              : "border-rose-300 text-rose-700 hover:bg-rose-50")
                          }
                        >
                          {g.is_public === false
                            ? t.restoreToCommunity
                            : t.hideFromCommunity}
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
              {listQ.data.items.length === 0 && (
                <tr>
                  <td
                    colSpan={editable ? 11 : 10}
                    className="px-3 py-6 text-center text-slate-500"
                  >
                    {t.emptyState}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {editable && editing && (
        <EditGatewayModal
          gatewayId={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["gateways"] });
          }}
        />
      )}

      {visTarget && (
        <ConfirmModal
          title={
            visTarget.makePublic ? t.confirmRestoreTitle : t.confirmHideTitle
          }
          body={
            <>
              <div>{visTarget.makePublic ? t.confirmRestoreBody : t.confirmHideBody}</div>
              <div className="mt-2 font-mono text-xs text-slate-500">
                {visTarget.code}
              </div>
              {visError && (
                <div className="mt-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-800">
                  {visError}
                </div>
              )}
            </>
          }
          confirmLabel={visMutation.isPending ? t.visibilityUpdating : t.confirmYes}
          danger={!visTarget.makePublic}
          onConfirm={() =>
            visMutation.mutate({ id: visTarget.id, makePublic: visTarget.makePublic })
          }
          onCancel={() => {
            setVisTarget(null);
            setVisError(null);
          }}
        />
      )}
    </>
  );
}

function PendingGatewaysTab() {
  const pendingQ = useQuery({
    queryKey: ["gateways", "admin", "pending"],
    queryFn: () => listPendingGateways(),
  });

  const tp = t.pending;

  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{tp.title}</h2>
      </div>

      <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        {tp.banner}
      </div>

      {pendingQ.isLoading && (
        <div className="text-sm text-slate-500">{tp.loading}</div>
      )}
      {pendingQ.isError && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {tp.listError}
        </div>
      )}

      {pendingQ.data && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                {tp.tableHeaders.map((h, i) => (
                  <th
                    key={h || `pcol-${i}`}
                    className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-slate-500"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {pendingQ.data.items.map((g, i) => (
                <tr key={g.id}>
                  <td className="px-3 py-2 text-right font-mono text-xs text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2 font-mono text-xs">{g.code}</td>
                  <td className="px-3 py-2">{g.name}</td>
                  <td className="px-3 py-2 font-mono text-xs">{g.latitude.toFixed(4)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{g.longitude.toFixed(4)}</td>
                  <td className="px-3 py-2">{g.frequency_mhz}</td>
                  <td className="px-3 py-2 text-xs">{g.source_type}</td>
                  <td className="px-3 py-2 text-xs">{g.contributor_email ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {new Date(g.created_at).toLocaleString("vi-VN")}
                  </td>
                </tr>
              ))}
              {pendingQ.data.items.length === 0 && (
                <tr>
                  <td colSpan={tp.tableHeaders.length} className="px-3 py-6 text-center text-slate-500">
                    {tp.emptyState}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function CreateGatewayTab() {
  const qc = useQueryClient();
  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">{t.createTitle}</h2>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <CreateGatewayForm
          onCreated={() => {
            qc.invalidateQueries({ queryKey: ["gateways"] });
          }}
        />
      </div>
    </>
  );
}

const STATE_BADGE_STYLE = {
  online: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  offline: "bg-rose-50 text-rose-700 ring-rose-200",
  never_seen: "bg-slate-100 text-slate-600 ring-slate-200",
  unknown: "bg-slate-50 text-slate-500 ring-slate-200",
};

/**
 * @param {{ state: "online" | "offline" | "never_seen" | "unknown", lastSeenAt: string | null }} props
 */
function StateBadge({ state, lastSeenAt }) {
  const label = t.state[state] ?? t.state.unknown;
  const tooltip =
    t.state.lastSeenPrefix +
    (lastSeenAt ? new Date(lastSeenAt).toLocaleString("vi-VN") : t.state.lastSeenNever);
  return (
    <span
      title={tooltip}
      className={
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset " +
        (STATE_BADGE_STYLE[state] ?? STATE_BADGE_STYLE.unknown)
      }
    >
      <span
        className={
          "h-1.5 w-1.5 rounded-full " +
          (state === "online"
            ? "bg-emerald-500"
            : state === "offline"
              ? "bg-rose-500"
              : "bg-slate-400")
        }
      />
      {label}
    </span>
  );
}

/**
 * @param {{ gatewayId: string, onClose: () => void, onSaved: () => void }} props
 */
function EditGatewayModal({ gatewayId, onClose, onSaved }) {
  const detailQ = useQuery({
    queryKey: ["gateway", gatewayId],
    queryFn: () => getGateway(gatewayId),
    staleTime: 0,
  });

  const m = useMutation({
    mutationFn: (
      /** @type {{ etag: string, patch: import("../api/client.js").GatewayPatchRequestT }} */ args,
    ) => patchGateway(gatewayId, args.etag, args.patch),
    onSuccess: onSaved,
  });

  return (
    <Modal title={t.editTitle} onClose={onClose}>
      {detailQ.isLoading && (
        <div className="text-sm text-slate-500">{t.loading}</div>
      )}
      {detailQ.isError && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          {t.detailError}
        </div>
      )}
      {detailQ.data && (
        <EditGatewayForm
          initial={detailQ.data.gateway}
          etag={detailQ.data.etag}
          submitting={m.isPending}
          error={m.isError && m.error instanceof ApiError ? m.error : null}
          onCancel={onClose}
          onSubmit={(patch, etag) => m.mutate({ etag, patch })}
        />
      )}
    </Modal>
  );
}

/**
 * @param {{
 *   initial: import("../api/client.js").GatewayT,
 *   etag: string | null,
 *   submitting: boolean,
 *   error: ApiError | null,
 *   onCancel: () => void,
 *   onSubmit: (patch: import("../api/client.js").GatewayPatchRequestT, etag: string) => void,
 * }} props
 */
function EditGatewayForm({ initial, etag, submitting, error, onCancel, onSubmit }) {
  const [name, setName] = useState(initial.name);
  const [altitudeM, setAltitudeM] = useState(String(initial.altitude_m));
  const [antennaHeightM, setAntennaHeightM] = useState(String(initial.antenna_height_m));
  const [antennaGainDbi, setAntennaGainDbi] = useState(String(initial.antenna_gain_dbi));
  const [txPowerDbm, setTxPowerDbm] = useState(String(initial.tx_power_dbm));
  // "" = auto (= null phía BE); enum literal = ghim. Dùng string để bind <select>.
  const initialManualState = initial.manual_state_override ?? "";
  const [manualState, setManualState] = useState(
    /** @type {"" | "online" | "offline" | "never_seen"} */ (initialManualState),
  );
  const [etagAlert, setEtagAlert] = useState(false);

  /** @param {import("react").FormEvent} e */
  function handleSubmit(e) {
    e.preventDefault();
    if (!etag) {
      setEtagAlert(true);
      return;
    }
    /** @type {import("../api/client.js").GatewayPatchRequestT} */
    const patch = {};
    if (name !== initial.name) patch.name = name;
    if (Number(altitudeM) !== initial.altitude_m) patch.altitude_m = Number(altitudeM);
    if (Number(antennaHeightM) !== initial.antenna_height_m) patch.antenna_height_m = Number(antennaHeightM);
    if (Number(antennaGainDbi) !== initial.antenna_gain_dbi) patch.antenna_gain_dbi = Number(antennaGainDbi);
    if (Number(txPowerDbm) !== initial.tx_power_dbm) patch.tx_power_dbm = Number(txPowerDbm);
    if (manualState !== initialManualState) {
      // "" → null (clear ghim, BE distinguish exclude_unset → SET = NULL).
      patch.manual_state_override = manualState === "" ? null : manualState;
    }

    if (Object.keys(patch).length === 0) {
      onCancel();
      return;
    }
    onSubmit(patch, etag);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <ReadonlyField label={t.fields.code} value={initial.code} />
        <ReadonlyField label={t.fields.id} value={initial.id} mono />
        <ReadonlyField label={t.fields.lat} value={initial.latitude.toFixed(6)} mono />
        <ReadonlyField label={t.fields.lon} value={initial.longitude.toFixed(6)} mono />
        <Field label={t.fields.name} value={name} onChange={setName} />
        <Field label={t.fields.altitude} value={altitudeM} onChange={setAltitudeM} type="number" />
        <Field label={t.fields.antennaHeight} value={antennaHeightM} onChange={setAntennaHeightM} type="number" />
        <Field label={t.fields.antennaGain} value={antennaGainDbi} onChange={setAntennaGainDbi} type="number" />
        <Field label={t.fields.txPower} value={txPowerDbm} onChange={setTxPowerDbm} type="number" />
        <ReadonlyField label={t.fields.frequency} value={String(initial.frequency_mhz)} />
        <label className="block sm:col-span-2">
          <span className="block text-xs font-medium text-slate-700">{t.fields.manualState}</span>
          <select
            value={manualState}
            onChange={(e) =>
              setManualState(
                /** @type {"" | "online" | "offline" | "never_seen"} */ (e.target.value),
              )
            }
            className="mt-1 w-full rounded-md border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">{t.manualState.auto}</option>
            <option value="online">{t.manualState.online}</option>
            <option value="offline">{t.manualState.offline}</option>
            <option value="never_seen">{t.manualState.never_seen}</option>
          </select>
          <p className="mt-1 text-[11px] text-slate-500">{t.manualState.hint}</p>
        </label>
      </div>

      {etag && (
        <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="font-mono">{t.ifMatchLabel}:</span> {etag}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          <div className="font-semibold">{error.problem.title}</div>
          {error.problem.detail && <div className="mt-1">{error.problem.detail}</div>}
          {error.problem.code === "ETAG_MISMATCH" && (
            <div className="mt-1 text-xs text-red-600">
              {t.etagMismatchHint}
            </div>
          )}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
        >
          {t.cancel}
        </button>
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {submitting ? t.savePending : t.save}
        </button>
      </div>

      {etagAlert && (
        <AlertModal
          title={t.etagMissingTitle}
          body={t.etagMissingAlert}
          onClose={() => setEtagAlert(false)}
        />
      )}
    </form>
  );
}

/**
 * @param {{ onCreated: () => void }} props
 */
function CreateGatewayForm({ onCreated }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [latitude, setLatitude] = useState("16.0544");
  const [longitude, setLongitude] = useState("108.2022");
  const [altitudeM, setAltitudeM] = useState("0");
  const [antennaHeightM, setAntennaHeightM] = useState("10");
  const [antennaGainDbi, setAntennaGainDbi] = useState("2");
  const [txPowerDbm, setTxPowerDbm] = useState("14");
  const [freq, setFreq] = useState(/** @type {433|868|915|923} */ (923));

  const m = useMutation({
    mutationFn: createGateway,
    onSuccess: () => {
      setCode("");
      setName("");
      onCreated();
    },
  });

  /** @param {import("react").FormEvent} e */
  function handleSubmit(e) {
    e.preventDefault();
    m.mutate({
      code,
      name,
      latitude: Number(latitude),
      longitude: Number(longitude),
      altitude_m: Number(altitudeM),
      antenna_height_m: Number(antennaHeightM),
      antenna_gain_dbi: Number(antennaGainDbi),
      tx_power_dbm: Number(txPowerDbm),
      frequency_mhz: freq,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <Field label={t.fields.code} value={code} onChange={setCode} required />
        <Field label={t.fields.name} value={name} onChange={setName} required />
        <Field label={t.fields.latitude} value={latitude} onChange={setLatitude} type="number" required />
        <Field label={t.fields.longitude} value={longitude} onChange={setLongitude} type="number" required />
        <Field label={t.fields.altitude} value={altitudeM} onChange={setAltitudeM} type="number" />
        <Field label={t.fields.antennaHeight} value={antennaHeightM} onChange={setAntennaHeightM} type="number" />
        <Field label={t.fields.antennaGain} value={antennaGainDbi} onChange={setAntennaGainDbi} type="number" />
        <Field label={t.fields.txPower} value={txPowerDbm} onChange={setTxPowerDbm} type="number" />
        <label className="block">
          <span className="block text-xs font-medium text-slate-700">{t.fields.frequency}</span>
          <select
            value={freq}
            onChange={(e) => setFreq(/** @type {433|868|915|923} */ (Number(e.target.value)))}
            className="mt-1 w-full rounded-md border-slate-300 px-2 py-1 text-sm"
          >
            {[433, 868, 915, 923].map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
      </div>

      {m.isError && m.error instanceof ApiError && (
        <div className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
          <div className="font-semibold">{m.error.problem.title}</div>
          {m.error.problem.detail && <div className="mt-1">{m.error.problem.detail}</div>}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="submit"
          disabled={m.isPending}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {m.isPending ? t.createPending : t.create}
        </button>
      </div>
    </form>
  );
}

/**
 * @param {{
 *   label: string,
 *   value: string,
 *   onChange: (v: string) => void,
 *   type?: string,
 *   required?: boolean,
 * }} props
 */
function Field({ label, value, onChange, type = "text", required }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-slate-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        step={type === "number" ? "0.0001" : undefined}
        className="mt-1 w-full rounded-md border-slate-300 px-2 py-1 text-sm focus:border-slate-500 focus:ring-slate-500"
      />
    </label>
  );
}

/**
 * @param {{ label: string, value: string, mono?: boolean }} props
 */
function ReadonlyField({ label, value, mono }) {
  return (
    <div>
      <span className="block text-xs font-medium text-slate-700">{label}</span>
      <div
        className={
          "mt-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-sm " +
          (mono ? "font-mono text-xs" : "")
        }
      >
        {value}
      </div>
    </div>
  );
}

/**
 * @param {{ title: string, onClose: () => void, children: import("react").ReactNode }} props
 */
function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
            aria-label={t.modalCloseAria}
          >
            ✕
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}
