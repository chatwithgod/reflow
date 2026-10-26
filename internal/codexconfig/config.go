// Package codexconfig manages only Codex's top-level openai_base_url setting.
// It never reads auth.json or copies the rest of config.toml into its state file.
package codexconfig

import (
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/pelletier/go-toml/v2"
	"github.com/pelletier/go-toml/v2/unstable"
)

const stateName = "reflow-routing.json"
const maxConfigSize = 2 << 20

type Preview struct {
	ConfigPath          string `json:"config_path"`
	Endpoint            string `json:"endpoint"`
	NativeProvider      bool   `json:"native_provider"`
	HasExistingOverride bool   `json:"has_existing_override"`
	AlreadyConnected    bool   `json:"already_connected"`
	RestoreAvailable    bool   `json:"restore_available"`
	Change              string `json:"change"`
	RestartRequired     bool   `json:"restart_required"`
}

type State struct {
	Version         int    `json:"version"`
	Endpoint        string `json:"endpoint"`
	OriginalPresent bool   `json:"original_present"`
	OriginalValue   string `json:"original_value,omitempty"`
	OriginalRaw     string `json:"original_raw,omitempty"`
	CreatedConfig   bool   `json:"created_config"`
}

type field struct {
	present              bool
	value                string
	keyStart, start, end int
}

func Endpoint(value string) (string, error) {
	u, err := url.Parse(value)
	if err != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return "", errors.New("endpoint must be a loopback HTTP origin")
	}
	host := strings.ToLower(u.Hostname())
	ip := net.ParseIP(host)
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return "", errors.New("endpoint must use localhost or a loopback IP")
	}
	if u.Host == "" {
		return "", errors.New("endpoint host is missing")
	}
	u.Path = ""
	u.RawPath = ""
	return u.String(), nil
}

func paths(home string) (string, string, error) {
	if strings.TrimSpace(home) == "" {
		return "", "", errors.New("Codex home is required")
	}
	root, err := filepath.Abs(home)
	if err != nil {
		return "", "", errors.New("invalid Codex home")
	}
	return filepath.Join(root, "config.toml"), filepath.Join(root, stateName), nil
}

func read(path string) ([]byte, os.FileMode, bool, error) {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil, 0600, false, nil
	}
	if err != nil {
		return nil, 0, false, errors.New("cannot inspect configuration file")
	}
	if !info.Mode().IsRegular() {
		return nil, 0, false, errors.New("configuration must be a regular file; symbolic links are not rewritten")
	}
	if info.Size() > maxConfigSize {
		return nil, 0, false, errors.New("configuration file is too large")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, 0, false, errors.New("cannot read configuration file")
	}
	return b, info.Mode().Perm(), true, nil
}

func inspect(data []byte) (field, bool, error) {
	offset := 0
	if bytes.HasPrefix(data, []byte{0xef, 0xbb, 0xbf}) {
		offset = 3
	}
	source := data[offset:]
	var values map[string]any
	if err := toml.Unmarshal(source, &values); err != nil {
		return field{}, false, errors.New("invalid Codex TOML; no changes made")
	}
	native := true
	if provider, ok := values["model_provider"]; ok {
		native = provider == "openai"
	}
	value := ""
	present := false
	if v, ok := values["openai_base_url"]; ok {
		var valid bool
		value, valid = v.(string)
		if !valid {
			return field{}, native, errors.New("openai_base_url must be a string")
		}
		present = true
	}
	var parser unstable.Parser
	parser.Reset(source)
	table := false
	for parser.NextExpression() {
		node := parser.Expression()
		if node.Kind == unstable.Table || node.Kind == unstable.ArrayTable {
			table = true
		}
		if table || node.Kind != unstable.KeyValue {
			continue
		}
		keys := node.Key()
		var names []string
		keyStart := 0
		for keys.Next() {
			if len(names) == 0 {
				keyStart = int(keys.Node().Raw.Offset) + offset
			}
			names = append(names, string(keys.Node().Data))
		}
		if len(names) == 1 && names[0] == "openai_base_url" {
			raw := node.Value().Raw
			start := int(raw.Offset) + offset
			return field{present: true, value: value, keyStart: keyStart, start: start, end: start + int(raw.Length)}, native, nil
		}
	}
	if parser.Error() != nil || present {
		return field{}, native, errors.New("cannot locate top-level openai_base_url safely")
	}
	return field{}, native, nil
}

func loadState(path string) (*State, error) {
	b, _, exists, err := read(path)
	if err != nil || !exists {
		return nil, err
	}
	var s State
	if json.Unmarshal(b, &s) != nil || s.Version != 1 {
		return nil, errors.New("invalid Reflow routing state")
	}
	if _, err := Endpoint(s.Endpoint); err != nil {
		return nil, errors.New("invalid Reflow routing state endpoint")
	}
	if s.OriginalPresent {
		check, _, err := inspect([]byte("openai_base_url = " + s.OriginalRaw + "\n"))
		if err != nil || !check.present || check.value != s.OriginalValue {
			return nil, errors.New("invalid original routing value")
		}
		encoded := []byte("openai_base_url = " + s.OriginalRaw + "\n")
		if string(encoded[check.start:check.end]) != s.OriginalRaw {
			return nil, errors.New("rollback state contains more than the original value")
		}
	}
	return &s, nil
}

func Inspect(home, endpoint string) (Preview, error) {
	endpoint, err := Endpoint(endpoint)
	if err != nil {
		return Preview{}, err
	}
	config, state, err := paths(home)
	if err != nil {
		return Preview{}, err
	}
	b, _, _, err := read(config)
	if err != nil {
		return Preview{}, err
	}
	f, native, err := inspect(b)
	if err != nil {
		return Preview{}, err
	}
	s, err := loadState(state)
	if err != nil {
		return Preview{}, err
	}
	quoted, _ := json.Marshal(endpoint)
	return Preview{ConfigPath: config, Endpoint: endpoint, NativeProvider: native, HasExistingOverride: f.present, AlreadyConnected: f.present && f.value == endpoint, RestoreAvailable: s != nil, Change: "openai_base_url = " + string(quoted)}, nil
}

func replaceValue(data []byte, f field, value []byte) []byte {
	if f.present {
		return append(append(append([]byte{}, data[:f.start]...), value...), data[f.end:]...)
	}
	offset := 0
	if bytes.HasPrefix(data, []byte{0xef, 0xbb, 0xbf}) {
		offset = 3
	}
	newline := "\n"
	if bytes.Contains(data, []byte("\r\n")) {
		newline = "\r\n"
	}
	out := append([]byte{}, data[:offset]...)
	out = append(out, []byte("openai_base_url = ")...)
	out = append(out, value...)
	out = append(out, newline...)
	return append(out, data[offset:]...)
}

func removeValue(data []byte, f field) []byte {
	start := bytes.LastIndexByte(data[:f.keyStart], '\n') + 1
	if start == 0 && bytes.HasPrefix(data, []byte{0xef, 0xbb, 0xbf}) {
		start = 3
	}
	end := len(data)
	if n := bytes.IndexByte(data[f.end:], '\n'); n >= 0 {
		end = f.end + n + 1
	}
	if len(bytes.TrimSpace(data[start:f.keyStart])) == 0 && len(bytes.TrimSpace(data[f.end:end])) == 0 {
		return append(append([]byte{}, data[:start]...), data[end:]...)
	}
	return append(append([]byte{}, data[:f.keyStart]...), data[f.end:]...)
}

func writeAtomic(path string, data []byte, mode os.FileMode) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".reflow-write-*")
	if err != nil {
		return errors.New("cannot create configuration temporary file")
	}
	name := f.Name()
	defer os.Remove(name)
	if err = f.Chmod(mode); err == nil {
		_, err = f.Write(data)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return errors.New("cannot write configuration temporary file")
	}
	if os.Rename(name, path) != nil {
		return errors.New("cannot replace configuration file")
	}
	return nil
}

func lock(home string) (func(), error) {
	if err := os.MkdirAll(home, 0700); err != nil {
		return nil, errors.New("cannot create Codex home")
	}
	path := filepath.Join(home, ".reflow-routing.lock")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, errors.New("another configuration operation or a stale Reflow lock exists")
	}
	f.Close()
	return func() { _ = os.Remove(path) }, nil
}

func Connect(home, endpoint string) (Preview, error) {
	preview, err := Inspect(home, endpoint)
	if err != nil {
		return Preview{}, err
	}
	if !preview.NativeProvider {
		return preview, errors.New("a custom model_provider is selected; Reflow does not change provider identity automatically")
	}
	config, statePath, _ := paths(home)
	unlock, err := lock(filepath.Dir(config))
	if err != nil {
		return preview, err
	}
	defer unlock()
	data, mode, exists, err := read(config)
	if err != nil {
		return preview, err
	}
	f, native, err := inspect(data)
	if err != nil {
		return preview, err
	}
	if !native {
		return preview, errors.New("provider changed during configuration")
	}
	s, err := loadState(statePath)
	if err != nil {
		return preview, err
	}
	if s != nil && s.Endpoint != preview.Endpoint {
		return preview, errors.New("restore the previous Reflow connection before changing its endpoint")
	}
	if f.present && f.value == preview.Endpoint {
		return Inspect(home, preview.Endpoint)
	}
	if s != nil {
		if f.present != s.OriginalPresent || (f.present && f.value != s.OriginalValue) {
			return preview, errors.New("routing changed outside Reflow; no changes made")
		}
	} else {
		if f.present {
			u, e := url.Parse(f.value)
			if e != nil || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
				return preview, errors.New("original URL may contain credentials; it will not be saved in rollback state")
			}
		}
		s = &State{Version: 1, Endpoint: preview.Endpoint, OriginalPresent: f.present, OriginalValue: f.value, CreatedConfig: !exists}
		if f.present {
			s.OriginalRaw = string(data[f.start:f.end])
		}
		encoded, _ := json.MarshalIndent(s, "", "  ")
		if err := writeAtomic(statePath, append(encoded, '\n'), 0600); err != nil {
			return preview, err
		}
	}
	quoted, _ := json.Marshal(preview.Endpoint)
	updated := replaceValue(data, f, quoted)
	if _, _, err := inspect(updated); err != nil {
		return preview, errors.New("routing edit failed TOML validation")
	}
	latest, _, _, err := read(config)
	if err != nil || !bytes.Equal(latest, data) {
		return preview, errors.New("configuration changed during update; retry after reviewing it")
	}
	if err := writeAtomic(config, updated, mode); err != nil {
		return preview, err
	}
	result, err := Inspect(home, preview.Endpoint)
	result.RestartRequired = true
	return result, err
}

func Restore(home string) error {
	_, err := RestoreChanged(home)
	return err
}

// RestoreChanged reports whether routing actually changed; a no-op does not
// require the user to restart Codex.
func RestoreChanged(home string) (bool, error) {
	config, statePath, err := paths(home)
	if err != nil {
		return false, err
	}
	unlock, err := lock(filepath.Dir(config))
	if err != nil {
		return false, err
	}
	defer unlock()
	s, err := loadState(statePath)
	if err != nil {
		return false, err
	}
	if s == nil {
		return false, nil
	}
	data, mode, _, err := read(config)
	if err != nil {
		return false, err
	}
	f, _, err := inspect(data)
	if err != nil {
		return false, err
	}
	if f.present == s.OriginalPresent && (!f.present || f.value == s.OriginalValue) {
		return false, os.Remove(statePath)
	}
	if !f.present || f.value != s.Endpoint {
		return false, errors.New("routing was changed after Reflow connected; refusing to overwrite it")
	}
	var updated []byte
	if s.OriginalPresent {
		updated = replaceValue(data, f, []byte(s.OriginalRaw))
	} else {
		updated = removeValue(data, f)
	}
	if _, _, err := inspect(updated); err != nil {
		return false, errors.New("restore failed TOML validation")
	}
	latest, _, _, err := read(config)
	if err != nil || !bytes.Equal(latest, data) {
		return false, errors.New("configuration changed during restore")
	}
	if err := writeAtomic(config, updated, mode); err != nil {
		return false, err
	}
	if s.CreatedConfig && len(bytes.TrimSpace(bytes.TrimPrefix(updated, []byte{0xef, 0xbb, 0xbf}))) == 0 {
		if err := os.Remove(config); err != nil {
			return true, err
		}
	}
	return true, os.Remove(statePath)
}
