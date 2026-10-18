package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestChineseAndRequestIsolation(t *testing.T) {
	a, err := rank(request{Protocol: protocol, RequestID: "a", Query: "复查医院", Documents: []document{{ID: "a:1", Content: "复查医院尚未确定"}, {ID: "b:1", Content: "希望回答简短"}}})
	if err != nil || len(a.Hits) == 0 || a.Hits[0].ID != "a:1" {
		t.Fatalf("Chinese retrieval: %+v %v", a, err)
	}
	b, err := rank(request{Protocol: protocol, RequestID: "b", Query: "复查医院", Documents: []document{{ID: "different:1", Content: "字体大一些"}}})
	if err != nil || len(b.Hits) != 0 {
		t.Fatalf("corpus from previous request leaked: %+v %v", b, err)
	}
}

func TestProtocolAndDuplicates(t *testing.T) {
	for _, input := range []string{
		`{"protocol":"wrong","request_id":"a"}`,
		`{"protocol":"zhongan-memory-rank-v1","request_id":"a","actor":"override"}`,
		`{"protocol":"zhongan-memory-rank-v1","request_id":"a"} {}`,
		`{"protocol":"zhongan-memory-rank-v1","request_id":"a","documents":[{"id":"same","content":"one"},{"id":"same","content":"two"}]}`,
	} {
		if err := run(strings.NewReader(input), &bytes.Buffer{}); err == nil {
			t.Fatalf("accepted invalid protocol")
		}
	}
}

func TestDeterministicTieAndEmptyQuery(t *testing.T) {
	r := request{Protocol: protocol, RequestID: "a", Query: "same", Documents: []document{{ID: "z", Content: "same"}, {ID: "a", Content: "same"}}}
	out, err := rank(r)
	if err != nil || len(out.Hits) != 2 || out.Hits[0].ID != "a" {
		t.Fatalf("unstable ordering")
	}
	r.Query = "？！"
	out, err = rank(r)
	if err != nil || len(out.Hits) != 0 {
		t.Fatalf("punctuation must not retrieve arbitrary memories")
	}
}
