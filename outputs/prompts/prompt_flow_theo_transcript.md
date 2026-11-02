# Prompt Google Flow theo transcript tiếng Việt

Thời gian bám theo transcript.txt. Cảnh cuối bắt đầu 01:25 và kết thúc theo MP3 thực tế; chưa có mốc kết thúc trong transcript.

## Cách dùng

1. Dùng ảnh hai nhân vật đã tạo làm tham chiếu. Tạo ảnh đầu mỗi cảnh bằng KHỐI ẢNH CHUNG + prompt ảnh của cảnh.
2. Dùng ảnh đó làm Start frame trong chế độ tạo video của Flow. Nhập prompt chuyển động của cảnh + KHỐI VIDEO CHUNG.
3. Nếu Flow tạo clip dài hơn thời lượng bảng, cắt phần phù hợp trong CapCut. Các cảnh 2 giây chỉ cần một động tác ngắn; không tăng tốc toàn clip để nhét nhiều hành động.
4. Ghép theo MP3 tiếng Việt. Thêm chữ, phụ đề và số liệu trong CapCut, không yêu cầu Flow vẽ chữ.
5. Các nhân vật người cổ đại là minh họa hư cấu. Không xác định giới tính, diện mạo hay các hành động chăm sóc cụ thể của cá thể khảo cổ từ hoạt hình.

## KHỐI ẢNH CHUNG — thêm trước mỗi prompt ảnh

```text
Vertical 9:16. Hand-drawn 2D educational cartoon, thick slightly irregular black outlines, flat earthy colors, simple thin limbs, large expressive faces, minimal prehistoric backgrounds. Match the exact drawing style of the provided reference image. Clear readable silhouettes and consistent character proportions. Main action fills the middle of the frame. Keep the lower fifth uncluttered for subtitles added later. No text, no captions, no watermark, no graphic injury, no blood.

For prehistoric reconstruction scenes, use the same two fictional adults from the reference: A is the brown-haired bearded man wearing a ragged tan hide tunic; B is the black-haired woman with a tied-up ponytail wearing an ochre hide tunic. Preserve their faces, hairstyles and clothes. A represents recovery after an old injury: the lower part of his LEFT leg is absent, with a completely healed rounded stump, no open wound. His right leg is intact. Do not switch sides or regrow the missing limb. These are fictional visual stand-ins, not portraits of the actual archaeological individual. Modern archaeologists only appear in excavation scenes.
```

## KHỐI VIDEO CHUNG — thêm sau mỗi prompt chuyển động

```text
One continuous 2D animated shot. Preserve the input image's character identities, clothing, limb arrangement and hand-drawn style. Keep movements simple and physically coherent. Maintain the same missing left lower limb whenever character A is present. No new characters or props appearing suddenly. No scene cuts, no dialogue, no narration, no music, no subtitles, no text. Optional quiet environmental ambience only.
```

## 01 — 00:00–00:06 | Mở đầu: bị thương giữa thời tiền sử

Lời đọc: “Bạn nghĩ bị thương nặng thời tiền sử là hết đường sống… không một phòng mổ nào chờ sẵn.”

**Ảnh đầu:**
```text
Character A sits leaning against a rock outside a prehistoric cave at dusk. His healed left lower-limb stump is visible below the tunic, while his intact right foot rests on the ground. His hands rest on the rock beside him. He looks worried and isolated. Character B is not present. Medium-wide shot, distant empty forest, no modern objects.
```
**Chuyển động:**
```text
A looks slowly to his left, then to his right, searching for help. His shoulders sink and his eyebrows lift with worry. His hands remain supported on the rock and his legs keep their original positions. Gentle camera push toward his face. Target edit length: 6 seconds.
```

## 02 — 00:06–00:09 | Bộ xương ba mươi mốt nghìn năm tuổi

**Ảnh đầu:**
```text
A simplified archaeological skeleton lies partially exposed in pale cave soil, viewed from above. The lower third of the anatomical left lower leg and left foot are absent; the right leg and foot remain intact. Restrained educational illustration, clear anatomy at a simple cartoon level. No prehistoric living characters, no tools touching the bones, no writing.
```
**Chuyển động:**
```text
Slow overhead camera push toward the skeleton. A soft sweep of light reveals the bone outlines without moving or changing any bones. Keep the missing left lower leg anatomically consistent. Target edit length: 3 seconds.
```
Gợi ý dựng: thêm “31.000 NĂM TRƯỚC” bằng CapCut nếu cần.

## 03 — 00:09–00:16 | Khai quật trong hang Borneo

**Ảnh đầu:**
```text
Inside a limestone cave with tropical greenery visible at the entrance, a modern adult archaeologist wearing a beige field shirt and dark trousers kneels beside a marked excavation area. They hold a soft brush above loose soil around a partially exposed skeleton. The skeleton has an absent distal left lower leg and left foot. Medium-wide composition, respectful scientific excavation. No prehistoric living characters.
```
**Chuyển động:**
```text
The archaeologist uses two gentle, short brush strokes on loose soil beside the bones, then pauses to inspect the missing lower-leg area. Only the dirt shifts slightly; all bones stay fixed. The camera gently moves closer. Target edit length: 7 seconds.
```

## 04 — 00:16–00:22 | Dấu vết kể câu chuyện khác

**Ảnh đầu:**
```text
Close-up of a modern archaeologist's face inside the cave, looking down thoughtfully at an excavation just below the frame. Beige field shirt, a small brush held still at chest level, raised eyebrows and a curious expression. Soft cave light and simple rocky background.
```
**Chuyển động:**
```text
The archaeologist tilts their head, narrows their eyes in concentration, then lifts their eyebrows as they notice an important detail. Their brush stays still. Slow camera push-in, no flashbacks or accident reenactments. Target edit length: 6 seconds.
```

## 05 — 00:22–00:27 | Kết luận về ca cắt cụt

**Ảnh đầu:**
```text
Clean educational archaeological illustration on a warm beige background. Show a simplified front view of a human skeleton with its distal anatomical left lower leg and left foot absent. The remaining left tibia and fibula end at the same healed level. The right lower leg and foot are intact. No surgical action, no blood, no tools, no labels.
```
**Chuyển động:**
```text
The skeleton remains completely still. The camera slowly approaches the healed end of the left lower leg. A soft translucent amber halo draws attention to the healed ends without changing their shape. Target edit length: 5 seconds.
```
Không dựng cảnh phẫu thuật trẻ em hoặc mô tả dụng cụ cụ thể, vì transcript không xác định kỹ thuật.

## 06 — 00:27–00:33 | Xương đã lành, sống thêm nhiều năm

**Ảnh đầu:**
```text
Close-up educational illustration of healed lower-leg bone ends on a neutral beige background. The bone edges are smooth and rounded, representing a healed injury. Simple stylized scientific diagram, no exposed flesh, no surgery, no hands or tools, no lettering.
```
**Chuyển động:**
```text
Very slow camera movement around the already healed bone ends, with a gentle shift in lighting to make the rounded edges readable. Do not show bones actively growing or regenerating. Target edit length: 6 seconds.
```
Gợi ý dựng: thêm “SỐNG THÊM 6–9 NĂM” bằng CapCut ở khoảng 00:32.

## 07 — 00:33–00:38 | Thời đồ đá

**Ảnh đầu:**
```text
Wide view of a fictional prehistoric camp near a limestone cave in a tropical forest. A small fire, simple hide shelters, woven baskets and rough stones are visible. A sits on a low rock with his healed left lower-limb stump visible. B stands nearby. No metal, no wheels, no modern medical equipment.
```
**Chuyển động:**
```text
The fire flickers and a light breeze moves the leaves. A glances toward B while B turns slightly toward him. Gentle lateral camera drift establishes the camp. No one handles any wound. Target edit length: 5 seconds.
```

## 08 — 00:38–00:43 | Tiếp tục sống sau chấn thương

**Ảnh đầu:**
```text
Character A sits upright at a low camp work surface, sorting a few smooth stones with his hands. His right foot rests on the ground; his healed left lower-limb stump remains visible and unchanged. He looks focused and calm. Warm daylight, simple cave camp background, no walking or medical procedure.
```
**Chuyển động:**
```text
A picks up one smooth stone, examines it and places it beside another stone. He gives a small satisfied nod. Keep his seated posture and both leg positions unchanged. Static medium shot. Target edit length: 5 seconds.
```
Đây là hoạt động minh họa hư cấu, không khẳng định cá thể khảo cổ từng làm công việc này.

## 09 — 00:43–00:49 | Chưa biết chính xác cách điều trị

**Ảnh đầu:**
```text
The modern archaeologist kneels beside the excavation inside the limestone cave, holding a blank field notebook on one knee and looking thoughtfully at the remains. A pencil rests still in their hand. No treatment equipment, no invented ancient remedies, no visible writing in the notebook.
```
**Chuyển động:**
```text
The archaeologist looks from the bones to the blank notebook, pauses with the pencil above the page, then looks back at the remains thoughtfully. Keep the page blank. No reconstruction of surgery, bleeding control or herbal treatment. Target edit length: 6 seconds.
```

## 10 — 00:49–00:55 | Phát hiện và câu hỏi còn lại

**Ảnh đầu:**
```text
Over-the-shoulder view of the same modern archaeologist studying the excavated skeleton in the cave. The skeleton is still and partially embedded in soil. A warm shaft of light falls across the healed left lower-leg area. Restrained, reflective educational mood.
```
**Chuyển động:**
```text
Slow camera pullback from the healed bone area to include the archaeologist's thoughtful profile and the surrounding excavation. The archaeologist lowers the notebook slightly and continues observing. No celebratory gestures or invented discoveries. Target edit length: 6 seconds.
```

## 11 — 00:55–01:03 | Những ngày hồi phục

**Ảnh đầu:**
```text
Fictional reconstruction: A sits comfortably beside the campfire, his healed left lower-limb stump unchanged, right foot on the ground. A simple hide blanket lies across his shoulders and a wooden bowl rests on his lap. B is seated nearby, watching with a calm supportive expression. Medium two-person shot.
```
**Chuyển động:**
```text
A adjusts the hide blanket with one hand, then lifts the wooden bowl slightly and settles comfortably. B gives a small reassuring nod. Their movements are slow and modest; the fire flickers softly. Do not show the missing limb regrowing or an instantaneous recovery. Target edit length: 8 seconds.
```

## 12 — 01:03–01:05 | Mang thức ăn

**Ảnh đầu:**
```text
Close two-person shot at the camp: B holds one wooden bowl of soft food close to A's outstretched hands, ready to hand it over. A is seated, B is kneeling. Keep both pairs of hands clearly visible and the bowl centered. Same reference characters and clothing.
```
**Chuyển động:**
```text
B moves the bowl a short distance into A's waiting hands. A securely holds it; only then does B release it. One simple handoff, no eating or other actions. Static camera. Use approximately 2 seconds of the successful handoff in the edit.
```

## 13 — 01:05–01:07 | Một bờ vai để tựa

**Ảnh đầu:**
```text
A and B sit side by side on a broad rock. A looks tired and leans slightly toward B. B is ready to support his upper back with one hand. A's right foot is on the ground and his healed left lower-limb stump remains unchanged. Close medium shot, warm light.
```
**Chuyển động:**
```text
A gently leans his upper body against B's shoulder. B places one hand on his upper back to steady him. Neither character stands or walks. One small supportive gesture, static camera. Use approximately 2 seconds in the edit.
```

## 14 — 01:07–01:14 | Đêm bên đống lửa, cảnh tái dựng

**Ảnh đầu:**
```text
A and B sit beside a small campfire outside the cave at night. A has a hide blanket around his shoulders, with the same healed left lower-limb stump and intact right leg. B sits beside him calmly. Dark blue forest, warm orange firelight, quiet intimate medium-wide shot.
```
**Chuyển động:**
```text
The fire flickers. A slowly relaxes his shoulders while B remains seated beside him, blinking naturally and occasionally looking toward him. Gentle slow camera pullback. Calm companionship through the night, no time-lapse or dramatic healing. Target edit length: 7 seconds.
```
Gợi ý dựng: từ 01:09 đến 01:14 hiện nhãn nhỏ “Cảnh tái dựng minh họa” trong CapCut, phù hợp câu phân biệt hình dung và bằng chứng.

## 15 — 01:14–01:20 | Giữa thế giới khắc nghiệt

**Ảnh đầu:**
```text
Wide view from inside the cave looking toward a rainy tropical forest. A sits sheltered beside a small fire, and B sits within arm's reach. A's lower left leg remains absent and healed. Two additional fictional adult camp members sit further back, quietly sharing the shelter. The rain remains outside; no one is exposed to immediate danger.
```
**Chuyển động:**
```text
Rain falls outside the cave. One background adult gently places a piece of firewood beside the fire, while B shifts slightly closer to A. A looks around the group with a calmer expression. Keep the camera steady and all four people distinct. Target edit length: 6 seconds.
```

## 16 — 01:20–01:25 | Những bàn tay chăm sóc

**Ảnh đầu:**
```text
Close medium shot of A seated beside the fire and B seated next to him. B's hand is poised just above A's shoulder, ready to rest there. A looks tired but peaceful. Warm firelight illuminates their familiar faces. Simple uncluttered background, no extra hands.
```
**Chuyển động:**
```text
B gently places one hand on A's shoulder. A glances down at the hand, then turns his head toward B. His face softens with relief. One continuous supportive gesture, very slow camera push-in. Target edit length: 5 seconds.
```

## 17 — 01:25–hết MP3 | Một người chịu ở lại

**Ảnh đầu:**
```text
Continuation of the preceding composition: A and B sit close together beside the campfire, B's single hand already resting on A's shoulder. A is turned slightly toward B. Both faces are calm. Match their exact positions, lighting and clothing from the previous shot. Leave space above them for an optional closing caption added later.
```
**Chuyển động:**
```text
A gives B a small grateful smile. B returns a gentle smile and keeps her hand resting on his shoulder. Hold their final expressions with subtle blinking and flickering firelight. The camera slowly eases backward. Finish on a calm held composition. Trim this final shot to the actual end of the Vietnamese narration.
```
Gợi ý dựng: giữ hình thêm tối đa khoảng nửa giây sau lời cuối nếu nhịp dựng cho phép. Không tự kéo video tới đúng 90 giây nếu MP3 dài/ngắn hơn.

## Kiểm tra trước khi xuất

- Trái/phải theo cơ thể nhân vật, không theo phía màn hình. Tránh lật ngang clip làm đổi chân bị mất.
- Mất phần dưới cẳng chân trái, không phải mất cả chân hoặc cắt ngang đùi.
- Những cảnh chăm sóc là tái dựng; giữ câu giải thích ở 01:09–01:14.
- Trong phụ đề, ghép “31.” và “000” thành “31.000”; sửa “vết thương trí mạng” thành “vết thương chí mạng”. Nếu lỗi nằm trong âm thanh, cần sửa lời rồi tạo lại đoạn đó; sửa phụ đề không đổi âm thanh.
- Không tạo lại các cảnh đã có nếu nhân vật, chân trái và hành động đã khớp; có thể cắt sử dụng lại.
