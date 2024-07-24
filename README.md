# CombinedAudioTool
- A Tool for CombinedAudio.bin for Minecraft for New Nintendo 3DS Edition (MC3DS) with a plethora of Features.
- Only support Windows Platforms Officially, due to being built and made using some Windows API functions.

## Feature Set:
- Extract All FSB Soundbank Files in the Archive.
- Extract a FSB Soundbank File by Name/Sound-ID.
- Get File name(s) from Soundbank Files for easier recognition.
- Rename Extracted files to original filename(s).
- Rebuild `CombinedAudio.bin` with new Custom Audio Files.
- Extract Header from `CombinedAudio.bin`.
- Add padding to files automatically (Requires Original Extracted File).
- Collect all Sound Names/ID's.
- Rename all Segments to Original Filenames.
- Grab Segment File Sizes individually, or altogether.
- Updating your Script as new features become avaliable.
- Extract Audio from FSB Files (now including GCADPCM FSB Soundbank Files).
- Convert `*.wav` back into GCADPCM/DSADPCM.
- Restore CATool File Integrity.
- Encode Minecraft 3DS Music Files from Wave Files.
- Convert any Audio Filetype to Wave (requires FFMPEG).
- Install FFMPEG via Command Line.
- Add your own Custom Audio/Ambience/SFX to Minecraft 3DS.
- Get MetaData from `CombinedAudio.bin` Archive.

## Download(s):
- Download [Here](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases/download/v2.1/CATool.zip).
- Requires `Python 3.8+` and `Python STD` (Installed alongside Python).

## Usage:
```
python CATool.py
       --eca,  extract-ca     [CombinedAudioPATH]                            > Extracts All FSB Soundbank Files from the CombinedAudio.bin Archive.
       --fn,   find-sn        [SegmentFilePATH]                              > Find the Segment Name from an Extracted FSB Soundbank File via --eca Flag.
       --rs,   rename-s       [SegmentFilePATH]                              > Rename a Segment File FSB Soundbank File back to it's Original Filename.
       --gh,   get-header     [CombinedAudioPATH]                            > Extracts the Header from the CombinedAudio.bin Archive.
       --rca,  rebuild-ca     [SegmentOutFolderPATH]                         > Rebuilds the CombinedAudio.bin Archive via Segment Files.
       --ap,   add-padding    [OriginalFilePATH]       [ModifiedFilePATH]    > Adds padding to set the Modified File Equal to the Original File Size.
       --ne,   name-extract   [CombinedAudioPATH]      [Sound Name/ID]       > Extracts a FSB Soundbank File from the CombinedAudio.bin Archive via Name/SoundID.
       --ra,   rename-all     [SegmentFolderPATH]                            > Renames all Segment Files back to their original FSB Soundbank Filename(s).
       --gsid, get-soundid    [CombinedAudioPATH]                            > Gets all Sound Names/ID's and Dumps them to a *.txt File.
       --gssg, get-size-seg   [SegmentFilePATH]                              > Gets the size of a specific Segment Soundbank FSB File.
       --gs,   get-size       [SegmentOutFolderPATH]                         > Gets the size of all Segment Soundbank FSB Files.
       --exa,  extract-seg    [SegmentFilePATH]                              > Attempts to extract Audio from Segment Soundbank FSB Files.
       --cwav, convert-wave   [SegmentFilePATH]        [FileToConvertPATH]   > Convert Custom Audio to Nintendo 'GCADPCM'/'DSADPCM' Format (*.dsp).
       --pa,   play-audio     [WaveFilePATH]                                 > Play Audio from a Wave-File.
       --gmsc, generate-music [WaveFilePATH]                                 > Generates a Valid Music FSB Soundbank File for Minecraft 3DS Edition from a Wave File.
       --atw,  to-wave        [AudioFileToConvertToWavPATH]                  > Convert basically any Audio format like *.fsb, *.dsp or Formats like *.mp3 to Wave Format.
       --impg, inst-ffmpeg                                                   > Install FFMPEG to '.\extrcd\mpg\bin'.
       --efrw, ext-fsb-raw    [SegmentFilePATH]                              > Extracts the raw GCADPCM/DSPADPCM Audio from an *.fsb Soundbank File.
       --edrw, ext-dsp-raw    [GeneratedDspFilePATH]                         > Extracts the raw GCADPCM/DSPADPCM Audio from a Nintendo *.dsp Audio File.
       --rsnd, replace-snd    [SegmentFilePATH]        [DspFilePATH]         > Convert Nintendo *.dsp Audio File to *.fsb Soundbank File.
       --gmtd, get-metadata   [CombinedAudioPATH]                            > Get info such as Header-Size, Number of Audio Files, and if the CombinedAudio.bin Archive has been Modified.
       --upd,  update                                                        > Updates From Current Version to the Latest Version of 'CATool.py'.
       --rstr, restore                                                       > Basically an Emergancy Version of '--upd' that Wipes all Files from CATool and Reinstalls them.
       --h,    help                                                          > Displays this Message.
```
### Help Message:
```
python CATool.py --h
```
![image](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/assets/78656905/7d2d4adb-6f45-4484-85ee-c519ad9058b7)

## Sound ID's
```
0. thunder1
1. thunder2
2. explode1
3. explode2
4. rain1
5. rain2
6. shimmerblock
7. fire_crackle2
8. add_item1
9. add_item2
10. add_item3
11. break1
12. break2
13. place1
14. place2
15. remove_item1
16. remove_item2
17. rotate_item1
18. rotate_item2
19. death1
20. death3
21. grow1
22. grow4
23. empty_lava1
24. empty_lava2
25. empty1
26. empty2
27. fill_lava1
28. fill_lava2
29. fill1
30. fill2
31. splash
32. fallbig
33. fallsmall
34. weak1
35. weak2
36. weak3
37. hit1
38. hit2
39. hit3
40. cloth1
41. cloth2
42. cloth3
43. grass1
44. grass2
45. grass3
46. gravel1
47. gravel2
48. gravel3
49. sand1
50. sand2
51. sand3
52. snow1
53. snow2
54. snow3
55. stone1
56. stone2
57. stone3
58. wood1
59. wood2
60. wood3
61. in
62. out
63. fire
64. ignite
65. lava
66. lavapop
67. water
68. base
69. death
70. hurt1
71. hurt2
72. hurt3
73. idle1
74. idle2
75. idle3
76. takeoff
77. breathe1
78. breathe2
79. death
80. hit1
81. hit2
82. hit3
83. fireball4
84. hurt1
85. hurt2
86. plop
87. say1
88. say2
89. say3
90. step1
91. step2
92. hurt1
93. hurt2
94. hurt3
95. say1
96. say2
97. say3
98. step1
99. step2
100. step3
101. milk1
102. death
103. say1
104. say2
105. say3
106. death
107. hit1
108. hit2
109. hit3
110. idle1
111. idle2
112. idle3
113. portal
114. portal2
115. scream1
116. scream2
117. scream3
118. stare
119. hit1
120. hit2
121. wings1
122. wings3
123. wings5
124. growl2
125. growl3
126. affectionate_scream
127. charge
128. death
129. moan1
130. moan2
131. moan3
132. scream1
133. scream2
134. scream3
135. ambient1
136. attack_loop
137. curse
138. elder_death
139. elder_hit1
140. elder_idle3
141. flop1
142. guardian_death
143. 
144. land_death
145. land_hit1
146. land_idle1
147. angry1
148. death1
149. death2
150. idle1
151. idle2
152. idle3
153. idle4
154. idle5
155. spit1
156. spit2
157. hurt1
158. hurt2
159. hurt3
160. eat1
161. eat2
162. eat3
163. step1
164. step2
165. step3
166. step4
167. step5
168. swag
169. angry1
170. armor
171. breathe1
172. breathe2
173. breathe3
174. death
175. angry1
176. angry2
177. death
178. hit1
179. hit2
180. hit3
181. idle1
182. idle2
183. idle3
184. eat1
185. eat2
186. eat3
187. gallop1
188. gallop2
189. gallop3
190. hit1
191. hit2
192. hit3
193. idle1
194. idle2
195. idle3
196. jump
197. land
198. leather
199. death
200. hit1
201. hit2
202. hit3
203. idle1
204. idle2
205. idle3
206. soft1
207. soft2
208. soft3
209. wood1
210. wood2
211. wood3
212. death
213. hit1
214. hit2
215. hit3
216. idle1
217. idle2
218. idle3
219. idle2
220. death1
221. hurt2
222. step4
223. throw
224. death
225. hit1
226. hit2
227. hit3
228. walk1
229. walk2
230. walk3
231. ambient1
232. ambient2
233. ambient5
234. close1
235. close3
236. death1
237. death2
238. hurt_close1
239. hurt_close2
240. hurt1
241. hurt2
242. hurt3
243. open2
244. open3
245. shoot1
246. shoot4
247. hit1
248. hit2
249. hit3
250. big1
251. big2
252. big3
253. jump1
254. jump2
255. jump3
256. small1
257. small2
258. small3
259. death
260. pig_boost
261. pig_boost
262. pig_boost
263. say1
264. say2
265. say3
266. step1
267. step2
268. step3
269. hurt1
270. hurt2
271. hurt3
272. idle1
273. idle2
274. idle3
275. hop1
276. hop2
277. hop3
278. bunnymurder
279. say1
280. say2
281. say3
282. shear
283. step1
284. step2
285. step3
286. 
287. hit2
288. hit3
289. kill
290. say1
291. say2
292. say3
293. step1
294. step2
295. step3
296. death
297. hurt1
298. hurt2
299. hurt3
300. say1
301. say2
302. say3
303. step1
304. step2
305. step3
306. big1
307. big2
308. big3
309. small1
310. small2
311. small3
312. attack1
313. attack2
314. death1
315. death2
316. death3
317. hurt1
318. hurt2
319. hurt3
320. bow
321. death
322. say1
323. say2
324. say3
325. step1
326. step2
327. step3
328. ambient1
329. ambient2
330. death3
331. hurt1
332. hurt2
333. idle2
334. death1
335. hurt4
336. step3
337. death
338. haggle1
339. haggle3
340. hit1
341. hit2
342. hit3
343. idle1
344. idle2
345. idle3
346. no1
347. no2
348. yes1
349. yes2
350. death1
351. death2
352. hurt1
353. hurt2
354. hurt3
355. idle1
356. idle2
357. idle3
358. fangs
359. idle1
360. idle2
361. idle3
362. cast1
363. cast2
364. death1
365. death2
366. hurt1
367. hurt2
368. prepare_attack1
369. prepare_attack2
370. prepare_summon
371. prepare_wololo
372. idle1
373. idle2
374. death1
375. death2
376. hurt1
377. hurt2
378. charge1
379. charge2
380. ambient5
381. ambient1
382. ambient2
383. death1
384. death2
385. death3
386. hurt1
387. hurt2
388. hurt3
389. drink1
390. drink2
391. drink3
392. throw1
393. throw2
394. throw3
395. idle1
396. woodbreak
397. death
398. hurt1
399. shoot
400. spawn
401. bark1
402. bark2
403. bark3
404. death
405. growl1
406. growl2
407. hurt1
408. hurt2
409. hurt3
410. panting
411. shake
412. step1
413. step2
414. step3
415. whine
416. hiss1
417. hiss2
418. hitt1
419. hitt2
420. hitt3
421. meow1
422. meow2
423. meow3
424. purr1
425. purr2
426. purreow1
427. purreow2
428. idle1
429. idle4
430. idle1
431. idle2
432. step1
433. step2
434. warning1
435. warning2
436. hurt1
437. hurt2
438. death1
439. death2
440. death
441. hurt1
442. hurt2
443. remedy
444. unfect
445. say1
446. say2
447. step1
448. step2
449. step3
450. wood1
451. wood2
452. wood3
453. zpig1
454. zpig2
455. zpig3
456. zpigangry1
457. zpigangry2
458. zpigangry3
459. zpigdeath
460. zpighurt1
461. zpighurt2
462. say1
463. say2
464. say3
465. death
466. hurt1
467. hurt2
468. bass
469. bassattack
470. bd
471. harp
472. hat
473. pling
474. snare
475. portal
476. anvil_break
477. anvil_land
478. anvil_use
479. bowhit1
480. bowhit2
481. bowhit3
482. break
483. burp
484. chestclosed
485. chestopen
486. close
487. open
488. click
489. door_close
490. door_open
491. drink
492. eat1
493. eat2
494. eat3
495. fizz
496. fuse
497. glass1
498. glass2
499. glass3
500. levelup
501. orb
502. pop
503. pop2
504. swim1
505. swim3
506. swim4
507. hurt
508. toast
509. use_totem
510. camera1
511. camera2
512. camera3
513. ladder1
514. ladder2
515. ladder3
516. cloth1
517. cloth2
518. cloth3
519. grass1
520. grass2
521. grass3
522. gravel1
523. gravel2
524. gravel3
525. sand1
526. sand2
527. sand3
528. snow1
529. snow2
530. snow3
531. stone1
532. stone2
533. stone3
534. wood1
535. wood2
536. wood3
537. cloth1
538. cloth2
539. cloth3
540. grass1
541. grass2
542. grass3
543. gravel1
544. gravel2
545. gravel3
546. sand1
547. sand2
548. sand3
549. snow1
550. snow2
551. snow3
552. stone1
553. stone2
554. stone3
555. wood1
556. wood2
557. wood3
```
