import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { LegalEntity } from "@/lib/legal-entity/types";
import { INDIA_STATE_CODES } from "@/lib/branch/validate-branch";
import type { BranchFormErrors, BranchFormValues } from "@/lib/branch/validate-branch";

interface BranchFormProps {
  values: BranchFormValues;
  errors: BranchFormErrors;
  onChange: (values: BranchFormValues) => void;
  legalEntities: LegalEntity[];
  idPrefix?: string;
}

const STATE_OPTIONS = Object.entries(INDIA_STATE_CODES).sort((a, b) => a[1].localeCompare(b[1]));

export function BranchForm({ values, errors, onChange, legalEntities, idPrefix = "" }: BranchFormProps) {
  function update<K extends keyof BranchFormValues>(key: K, value: BranchFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("legalEntityId")}
            label="Legal entity"
            required
            error={errors.legalEntityId}
            description="The legal entity this branch operates under."
            className="sm:col-span-2"
          >
            <NativeSelect
              value={values.legalEntityId}
              onChange={(e) => update("legalEntityId", e.target.value)}
            >
              <option value="">Select a legal entity</option>
              {legalEntities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("name")} label="Branch name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField id={id("code")} label="Branch code" error={errors.code}>
            <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Address</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("addressLine1")} label="Address line 1" error={errors.addressLine1} className="sm:col-span-2">
            <Input
              value={values.addressLine1}
              onChange={(e) => update("addressLine1", e.target.value)}
            />
          </FormField>
          <FormField id={id("addressLine2")} label="Address line 2" error={errors.addressLine2} className="sm:col-span-2">
            <Input
              value={values.addressLine2}
              onChange={(e) => update("addressLine2", e.target.value)}
            />
          </FormField>
          <FormField id={id("city")} label="City" error={errors.city}>
            <Input value={values.city} onChange={(e) => update("city", e.target.value)} />
          </FormField>
          <FormField id={id("stateCode")} label="State / union territory" error={errors.stateCode}>
            <NativeSelect
              value={values.stateCode}
              onChange={(e) => update("stateCode", e.target.value)}
            >
              <option value="">Select a state</option>
              {STATE_OPTIONS.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("pincode")} label="PIN code" error={errors.pincode}>
            <Input value={values.pincode} onChange={(e) => update("pincode", e.target.value)} placeholder="560001" />
          </FormField>
          <FormField id={id("timezone")} label="Timezone" error={errors.timezone}>
            <Input
              value={values.timezone}
              onChange={(e) => update("timezone", e.target.value)}
              placeholder="Asia/Kolkata"
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Geofence</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Optional — capture coordinates now; the interactive map editor and geofence
          enforcement ship with Attendance.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id={id("latitude")} label="Latitude" error={errors.latitude}>
            <Input value={values.latitude} onChange={(e) => update("latitude", e.target.value)} placeholder="12.9716" />
          </FormField>
          <FormField id={id("longitude")} label="Longitude" error={errors.longitude}>
            <Input value={values.longitude} onChange={(e) => update("longitude", e.target.value)} placeholder="77.5946" />
          </FormField>
          <FormField id={id("geofenceRadiusM")} label="Geofence radius (m)" error={errors.geofenceRadiusM}>
            <Input
              value={values.geofenceRadiusM}
              onChange={(e) => update("geofenceRadiusM", e.target.value)}
              placeholder="200"
            />
          </FormField>
        </div>
      </section>
    </div>
  );
}
