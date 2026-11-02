import { Button } from '../../shared/ui/Button'

export interface HostnameRow {
  hostname: string
  is_primary: boolean
}
export interface InterfaceRow {
  name: string
  mac_address: string
}
export interface AddressRow {
  address: string
  interface_name: string
  is_primary: boolean
}
export interface NetworkRows {
  hostnames: HostnameRow[]
  interfaces: InterfaceRow[]
  ip_addresses: AddressRow[]
}

interface Props {
  value: NetworkRows
  onChange: (value: NetworkRows) => void
  errors: Record<string, string[]>
}

function CellInput({
  label,
  value,
  onChange,
  error,
  mono = true,
  placeholder,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string[]
  mono?: boolean
  placeholder?: string
}) {
  return (
    <>
      <input
        className={`field__control field__control--cell${mono ? ' mono' : ''}`}
        aria-label={label}
        aria-invalid={error?.length ? true : undefined}
        value={value}
        placeholder={placeholder}
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
      />
      {error?.map((message) => (
        <p className="field__error" key={message}>
          {message}
        </p>
      ))}
    </>
  )
}

/** Edits manually entered identifiers only. Discovered rows are owned by their source. */
export function NetworkEditor({ value, onChange, errors }: Props) {
  function patch<K extends keyof NetworkRows>(key: K, rows: NetworkRows[K]) {
    onChange({ ...value, [key]: rows })
  }
  function setPrimary<K extends 'hostnames' | 'ip_addresses'>(key: K, index: number) {
    patch(
      key,
      value[key].map((row, i) => ({ ...row, is_primary: i === index })) as NetworkRows[K],
    )
  }

  return (
    <div className="network-editor">
      {(['hostnames', 'interfaces', 'ip_addresses'] as const).map((kind) =>
        errors[kind] ? (
          <p className="field__error" key={kind}>
            {errors[kind].join(' ')}
          </p>
        ) : null,
      )}

      <fieldset className="fieldset">
        <legend className="field__label">Hostnames</legend>
        {value.hostnames.length > 0 && (
          <table className="data-table data-table--compact data-table--edit">
            <thead>
              <tr>
                <th scope="col">Hostname</th>
                <th scope="col">Primary</th>
                <th scope="col">
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {value.hostnames.map((row, index) => (
                <tr key={index}>
                  <td>
                    <CellInput
                      label={`Hostname ${index + 1}`}
                      value={row.hostname}
                      placeholder="sw-core-01.corp.example"
                      error={errors[`hostnames.${index}.hostname`]}
                      onChange={(hostname) =>
                        patch(
                          'hostnames',
                          value.hostnames.map((r, i) => (i === index ? { ...r, hostname } : r)),
                        )
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="radio"
                      name="primary-hostname"
                      aria-label={`Primary hostname ${index + 1}`}
                      checked={row.is_primary}
                      onChange={() => setPrimary('hostnames', index)}
                    />
                  </td>
                  <td>
                    <Button
                      variant="quiet"
                      onClick={() =>
                        patch('hostnames', value.hostnames.filter((_, i) => i !== index))
                      }
                    >
                      Remove<span className="visually-hidden"> hostname {index + 1}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Button
          onClick={() =>
            patch('hostnames', [
              ...value.hostnames,
              { hostname: '', is_primary: value.hostnames.length === 0 },
            ])
          }
        >
          Add hostname
        </Button>
      </fieldset>

      <fieldset className="fieldset">
        <legend className="field__label">Interfaces</legend>
        {value.interfaces.length > 0 && (
          <table className="data-table data-table--compact data-table--edit">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">MAC address</th>
                <th scope="col">
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {value.interfaces.map((row, index) => (
                <tr key={index}>
                  <td>
                    <CellInput
                      label={`Interface ${index + 1} name`}
                      value={row.name}
                      placeholder="eth0"
                      error={errors[`interfaces.${index}.name`]}
                      onChange={(name) =>
                        patch(
                          'interfaces',
                          value.interfaces.map((r, i) => (i === index ? { ...r, name } : r)),
                        )
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      label={`Interface ${index + 1} MAC address`}
                      value={row.mac_address}
                      placeholder="Optional"
                      error={errors[`interfaces.${index}.mac_address`]}
                      onChange={(mac_address) =>
                        patch(
                          'interfaces',
                          value.interfaces.map((r, i) => (i === index ? { ...r, mac_address } : r)),
                        )
                      }
                    />
                  </td>
                  <td>
                    <Button
                      variant="quiet"
                      onClick={() =>
                        patch('interfaces', value.interfaces.filter((_, i) => i !== index))
                      }
                    >
                      Remove<span className="visually-hidden"> interface {index + 1}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Button
          onClick={() => patch('interfaces', [...value.interfaces, { name: '', mac_address: '' }])}
        >
          Add interface
        </Button>
      </fieldset>

      <fieldset className="fieldset">
        <legend className="field__label">IP addresses</legend>
        {value.ip_addresses.length > 0 && (
          <table className="data-table data-table--compact data-table--edit">
            <thead>
              <tr>
                <th scope="col">Address</th>
                <th scope="col">Interface</th>
                <th scope="col">Primary</th>
                <th scope="col">
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {value.ip_addresses.map((row, index) => (
                <tr key={index}>
                  <td>
                    <CellInput
                      label={`IP address ${index + 1}`}
                      value={row.address}
                      placeholder="10.0.0.10"
                      error={errors[`ip_addresses.${index}.address`]}
                      onChange={(address) =>
                        patch(
                          'ip_addresses',
                          value.ip_addresses.map((r, i) => (i === index ? { ...r, address } : r)),
                        )
                      }
                    />
                  </td>
                  <td>
                    <select
                      className="field__control field__control--cell"
                      aria-label={`IP address ${index + 1} interface`}
                      value={row.interface_name}
                      onChange={(event) =>
                        patch(
                          'ip_addresses',
                          value.ip_addresses.map((r, i) =>
                            i === index ? { ...r, interface_name: event.target.value } : r,
                          ),
                        )
                      }
                    >
                      <option value="">None</option>
                      {value.interfaces
                        .filter((i) => i.name.trim())
                        .map((i) => (
                          <option key={i.name} value={i.name.trim()}>
                            {i.name.trim()}
                          </option>
                        ))}
                    </select>
                    {errors[`ip_addresses.${index}.interface_name`]?.map((m) => (
                      <p className="field__error" key={m}>
                        {m}
                      </p>
                    ))}
                  </td>
                  <td>
                    <input
                      type="radio"
                      name="primary-ip"
                      aria-label={`Primary IP address ${index + 1}`}
                      checked={row.is_primary}
                      onChange={() => setPrimary('ip_addresses', index)}
                    />
                  </td>
                  <td>
                    <Button
                      variant="quiet"
                      onClick={() =>
                        patch('ip_addresses', value.ip_addresses.filter((_, i) => i !== index))
                      }
                    >
                      Remove<span className="visually-hidden"> IP address {index + 1}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Button
          onClick={() =>
            patch('ip_addresses', [
              ...value.ip_addresses,
              { address: '', interface_name: '', is_primary: value.ip_addresses.length === 0 },
            ])
          }
        >
          Add IP address
        </Button>
      </fieldset>
      <p className="field__help">
        Optional. Identifiers discovered by integrations are managed by their source and are not
        edited here.
      </p>
    </div>
  )
}
