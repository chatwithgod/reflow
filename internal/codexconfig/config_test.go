package codexconfig

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConnectRestorePreservesUnrelatedConfiguration(t *testing.T) {
	for _, source := range []string{
		"# keep\nmodel='gpt-6.1-sol'\n[model_providers.demo]\napi_key='synthetic-private-key'\n",
		"# keep\r\n'openai_base_url' = 'https://example.invalid/v1' # comment\r\nmodel='gpt-6.1-sol'\r\n",
		"text = '''\nopenai_base_url='not a real key'\n'''\nopenai_base_url = \"https://example.invalid/v1\"\n",
	} {
		t.Run(source[:6], func(t *testing.T) {
			home := t.TempDir()
			path := filepath.Join(home, "config.toml")
			os.WriteFile(path, []byte(source), 0600)
			p, err := Connect(home, "http://127.0.0.1:18516")
			if err != nil || !p.AlreadyConnected {
				t.Fatalf("connect=%v %v", p, err)
			}
			state, _ := os.ReadFile(filepath.Join(home, stateName))
			if bytes.Contains(state, []byte("synthetic-private-key")) {
				t.Fatal("unrelated credentials copied")
			}
			if err := Restore(home); err != nil {
				t.Fatal(err)
			}
			actual, _ := os.ReadFile(path)
			if string(actual) != source {
				t.Fatalf("restore changed unrelated bytes:\n%s", actual)
			}
		})
	}
}

func TestRestorePreservesLaterUserEdits(t *testing.T) {
	home := t.TempDir()
	path := filepath.Join(home, "config.toml")
	os.WriteFile(path, []byte("model='original'\n"), 0600)
	if _, err := Connect(home, "http://127.0.0.1:18516"); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(path)
	b = bytes.ReplaceAll(b, []byte("'original'"), []byte("'user-changed'"))
	os.WriteFile(path, b, 0600)
	if err := Restore(home); err != nil {
		t.Fatal(err)
	}
	b, _ = os.ReadFile(path)
	if string(b) != "model='user-changed'\n" {
		t.Fatal("unrelated user edit lost")
	}
}

func TestNoPreviewWritesAndIdempotentApply(t *testing.T) {
	home := filepath.Join(t.TempDir(), "not-created")
	if _, err := Inspect(home, "http://127.0.0.1:18516"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(home); !os.IsNotExist(err) {
		t.Fatal("preview wrote files")
	}
	if p, err := Connect(home, "http://127.0.0.1:18516"); err != nil || !p.RestartRequired {
		t.Fatalf("first connect restart=%t err=%v", p.RestartRequired, err)
	}
	before, _ := os.ReadFile(filepath.Join(home, stateName))
	if p, err := Connect(home, "http://127.0.0.1:18516"); err != nil || p.RestartRequired {
		t.Fatalf("no-op connect restart=%t err=%v", p.RestartRequired, err)
	}
	after, _ := os.ReadFile(filepath.Join(home, stateName))
	if !bytes.Equal(before, after) {
		t.Fatal("original rollback replaced")
	}
	if changed, err := RestoreChanged(home); err != nil || !changed {
		t.Fatalf("first restore changed=%t err=%v", changed, err)
	}
	if changed, err := RestoreChanged(home); err != nil || changed {
		t.Fatalf("no-op restore changed=%t err=%v", changed, err)
	}
	if _, err := os.Stat(filepath.Join(home, "config.toml")); !os.IsNotExist(err) {
		t.Fatal("created empty config not restored")
	}
}

func TestConflictingRoutingAndSecretURLAreNotOverwritten(t *testing.T) {
	for _, source := range []string{"model_provider='cpa'\n", "openai_base_url='https://example.invalid/v1?key=synthetic-secret'\n", "openai_base_url='https://u:synthetic-secret@example.invalid'\n"} {
		home := t.TempDir()
		path := filepath.Join(home, "config.toml")
		os.WriteFile(path, []byte(source), 0600)
		_, err := Connect(home, "http://127.0.0.1:18516")
		if err == nil {
			t.Fatal("unsafe connection accepted")
		}
		b, _ := os.ReadFile(path)
		if string(b) != source {
			t.Fatal("configuration changed despite rejection")
		}
		if strings.Contains(err.Error(), "synthetic-secret") {
			t.Fatal("error disclosed a secret")
		}
	}
	home := t.TempDir()
	Connect(home, "http://127.0.0.1:18516")
	os.WriteFile(filepath.Join(home, "config.toml"), []byte("openai_base_url='http://localhost:9999'\n"), 0600)
	if Restore(home) == nil {
		t.Fatal("overwrote user's newer routing")
	}
}

func TestStalePreparedStateRecoversWithoutLosingOriginal(t *testing.T) {
	home := t.TempDir()
	source := "openai_base_url='https://example.invalid/v1'\n"
	os.WriteFile(filepath.Join(home, "config.toml"), []byte(source), 0600)
	Connect(home, "http://127.0.0.1:18516")
	// Simulate state being persisted but the config write not happening.
	os.WriteFile(filepath.Join(home, "config.toml"), []byte(source), 0600)
	if _, err := Connect(home, "http://127.0.0.1:18516"); err != nil {
		t.Fatal(err)
	}
	if err := Restore(home); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(home, "config.toml"))
	if string(b) != source {
		t.Fatal("lost original override")
	}
}
