"""Read-only frozen evaluation for B ONNX semantics plus existing gaze-down rule."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "ai/browser_ml/artifacts/retrained-v2-3class-b/20260809T180352Z"
FROZEN = ROOT / "ai/experiments/focus_v3_aug/runs/20260808T124939Z/frozen_test_manifest.json"
CLASSES = ("focus", "drowsy", "gaze_down", "gaze_side")

def main() -> None:
    import numpy as np
    from sklearn import metrics as sk
    meta=json.loads((B/'metadata.json').read_text(encoding='utf-8')); features=meta['feature_names']
    data=[r for r in json.loads(FROZEN.read_text(encoding='utf-8'))['rows'] if r['label'] in CLASSES]
    x=np.asarray([[float(r[n]) for n in features] for r in data],dtype=np.float32); y=np.asarray([r['label'] for r in data])
    model=pickle.loads((B/'focus-state-v2-3class-b.offline.pkl').read_bytes()); pred=model.predict(x)
    final=[]
    for row, model_state in zip(data,pred):
        strong_drowsy=float(row['continuous_eye_closed_sec']) >= 10
        gaze_down=float(row['iris_y_ratio']) >= .62
        final.append('drowsy' if strong_drowsy else 'gaze_down' if gaze_down else model_state)
    final=np.asarray(final); report=sk.classification_report(y,final,labels=CLASSES,output_dict=True,zero_division=0)
    print('FocusAI Hybrid Candidate Evaluation')
    for name,fn in [('Accuracy',sk.accuracy_score),('Balanced Accuracy',sk.balanced_accuracy_score)]: print(f'{name}: {fn(y,final):.2%}')
    print(f"Macro F1: {sk.f1_score(y,final,labels=CLASSES,average='macro',zero_division=0):.2%}")
    print(f"Weighted F1: {sk.f1_score(y,final,labels=CLASSES,average='weighted',zero_division=0):.2%}")
    for c in CLASSES: print(c, report[c])
    print('Confusion Matrix:',sk.confusion_matrix(y,final,labels=CLASSES).tolist())
    mask=np.isin(y,['focus','drowsy','gaze_side']); print('B 49 drowsy recall:',float(json.loads((B/'metrics.json').read_text(encoding='utf-8'))['metrics']['per_class']['drowsy']['recall'])); print('Hybrid 49 drowsy recall:',sk.recall_score(y[mask],final[mask],labels=['focus','drowsy','gaze_side'],average=None,zero_division=0)[1])
    gd=y=='gaze_down'; print('Gaze Down Test:',int(gd.sum()),'Correct:',int((final[gd]=='gaze_down').sum()),'Recall:',float((final[gd]=='gaze_down').mean()))
if __name__=='__main__': main()
