import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type {
  LegalEntityFormErrors,
  LegalEntityFormValues,
} from "@/lib/legal-entity/validate-legal-entity";

interface LegalEntityFormProps {
  values: LegalEntityFormValues;
  errors: LegalEntityFormErrors;
  onChange: (values: LegalEntityFormValues) => void;
  idPrefix?: string;
}

export function LegalEntityForm({ values, errors, onChange, idPrefix = "" }: LegalEntityFormProps) {
  function update<K extends keyof LegalEntityFormValues>(key: K, value: LegalEntityFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("name")}
            label="Company name"
            required
            error={errors.name}
            description="The legally registered company that employs your workforce."
            className="sm:col-span-2"
          >
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField
            id={id("registeredAddress")}
            label="Registered address"
            error={errors.registeredAddress}
            className="sm:col-span-2"
          >
            <Input
              value={values.registeredAddress}
              onChange={(e) => update("registeredAddress", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Statutory identifiers</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Optional — add these when you have them. They can be filled in later.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("pan")} label="PAN" error={errors.pan}>
            <Input
              value={values.pan}
              onChange={(e) => update("pan", e.target.value)}
              placeholder="ABCDE1234F"
            />
          </FormField>
          <FormField id={id("gstin")} label="GSTIN" error={errors.gstin}>
            <Input
              value={values.gstin}
              onChange={(e) => update("gstin", e.target.value)}
              placeholder="29ABCDE1234F1Z5"
            />
          </FormField>
          <FormField id={id("tan")} label="TAN" error={errors.tan}>
            <Input value={values.tan} onChange={(e) => update("tan", e.target.value)} />
          </FormField>
          <FormField id={id("cin")} label="CIN" error={errors.cin}>
            <Input value={values.cin} onChange={(e) => update("cin", e.target.value)} />
          </FormField>
          <FormField id={id("pfCode")} label="PF establishment code" error={errors.pfCode}>
            <Input value={values.pfCode} onChange={(e) => update("pfCode", e.target.value)} />
          </FormField>
          <FormField id={id("esiCode")} label="ESI code" error={errors.esiCode}>
            <Input value={values.esiCode} onChange={(e) => update("esiCode", e.target.value)} />
          </FormField>
          <FormField id={id("lwfReg")} label="Labour welfare fund (LWF) registration" error={errors.lwfReg}>
            <Input value={values.lwfReg} onChange={(e) => update("lwfReg", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Authorized signatory</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("signatoryName")} label="Signatory name" error={errors.signatoryName}>
            <Input
              value={values.signatoryName}
              onChange={(e) => update("signatoryName", e.target.value)}
            />
          </FormField>
          <FormField
            id={id("signatoryDesignation")}
            label="Signatory designation"
            error={errors.signatoryDesignation}
          >
            <Input
              value={values.signatoryDesignation}
              onChange={(e) => update("signatoryDesignation", e.target.value)}
            />
          </FormField>
        </div>
      </section>
    </div>
  );
}
