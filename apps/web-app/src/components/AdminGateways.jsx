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
import { AlertModal } from "./Modal.jsx";
import { strings } from "../strings.js";

const t = strings.adminGateways;

// Tạm ẩn create-gateway flow — DB seed/migration đảm nhiệm.
// Bật lại bằng cách set true; modal + mutation vẫn còn nguyên.
const ENABLE_CREATE_GATEWAY = false;

/**
 * @param {{ editable?: boolean }} props
 */
export function AdminGateways({ editable = false }) {
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["gateways", "admin"],
    queryFn: () => listGateways(),
  });

  const [editing, setEditing] = useState(
    /** @type {string | null} */ (null),
  );
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto max-w-6xl px-4 py-4 md:px-6 md:py-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">
          {t.title}
        </h2>
        {ENABLE_CREATE_GATEWAY && (
          <button
            onClick={() => setCreating(true)}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          >
            {t.addButton}
          </button>
        )}
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
                  </td>
                  {editable && (
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => setEditing(g.id)}
                        className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
                      >
                        {t.editButton}
                      </button>
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

      {ENABLE_CREATE_GATEWAY && creating && (
        <CreateGatewayModal
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["gateways"] });
          }}
        />
      )}
    </div>
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
 * @param {{ onClose: () => void, onCreated: () => void }} props
 */
function CreateGatewayModal({ onClose, onCreated }) {
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
    onSuccess: onCreated,
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
    <Modal title={t.createTitle} onClose={onClose}>
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
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
          >
            {t.cancel}
          </button>
          <button
            type="submit"
            disabled={m.isPending}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {m.isPending ? t.createPending : t.create}
          </button>
        </div>
      </form>
    </Modal>
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
