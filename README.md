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
- Change between Interleaved/Flat/Weaved for `SegmentFile`.

## Download(s):
- Download [Here](https://github.com/Minecraft-3DS-Community/CombinedAudioTool/releases/download/v2.3/CATool.zip).
- Requires `Python 3.8+` and `Python STD` (Installed alongside Python).

## Usage:
```

THIS IS A COMMAND LINE TOOL! YOU MUST USE POWERSHELL (or) CMD PROMPT TO USE. 

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
       --chmd, change-mode    [SegmentFilePATH]        [Integer (0-2)]       > Change the Mode the File is Played (interleaved, flat, and weaved). *May Enhance or Denhance the SFX.
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
thunder1 - segment_0.fsb
thunder2 - segment_1.fsb
explode1 - segment_2.fsb
explode2 - segment_3.fsb
rain1 - segment_4.fsb
rain2 - segment_5.fsb
shimmerblock - segment_6.fsb
fire_crackle2 - segment_7.fsb
add_item1 - segment_8.fsb
add_item2 - segment_9.fsb
add_item3 - segment_10.fsb
break1 - segment_11.fsb
break2 - segment_12.fsb
place1 - segment_13.fsb
place2 - segment_14.fsb
remove_item1 - segment_15.fsb
remove_item2 - segment_16.fsb
rotate_item1 - segment_17.fsb
rotate_item2 - segment_18.fsb
death1 - segment_19.fsb
death3 - segment_20.fsb
grow1 - segment_21.fsb
grow4 - segment_22.fsb
empty_lava1 - segment_23.fsb
empty_lava2 - segment_24.fsb
empty1 - segment_25.fsb
empty2 - segment_26.fsb
fill_lava1 - segment_27.fsb
fill_lava2 - segment_28.fsb
fill1 - segment_29.fsb
fill2 - segment_30.fsb
splash - segment_31.fsb
fallbig - segment_32.fsb
fallsmall - segment_33.fsb
weak1 - segment_34.fsb
weak2 - segment_35.fsb
weak3 - segment_36.fsb
hit1 - segment_37.fsb
hit2 - segment_38.fsb
hit3 - segment_39.fsb
cloth1 - segment_40.fsb
cloth2 - segment_41.fsb
cloth3 - segment_42.fsb
grass1 - segment_43.fsb
grass2 - segment_44.fsb
grass3 - segment_45.fsb
gravel1 - segment_46.fsb
gravel2 - segment_47.fsb
gravel3 - segment_48.fsb
sand1 - segment_49.fsb
sand2 - segment_50.fsb
sand3 - segment_51.fsb
snow1 - segment_52.fsb
snow2 - segment_53.fsb
snow3 - segment_54.fsb
stone1 - segment_55.fsb
stone2 - segment_56.fsb
stone3 - segment_57.fsb
wood1 - segment_58.fsb
wood2 - segment_59.fsb
wood3 - segment_60.fsb
in - segment_61.fsb
out - segment_62.fsb
fire - segment_63.fsb
ignite - segment_64.fsb
lava - segment_65.fsb
lavapop - segment_66.fsb
water - segment_67.fsb
base - segment_68.fsb
death - segment_69.fsb
hurt1 - segment_70.fsb
hurt2 - segment_71.fsb
hurt3 - segment_72.fsb
idle1 - segment_73.fsb
idle2 - segment_74.fsb
idle3 - segment_75.fsb
takeoff - segment_76.fsb
breathe1 - segment_77.fsb
breathe2 - segment_78.fsb
death - segment_79.fsb
hit1 - segment_80.fsb
hit2 - segment_81.fsb
hit3 - segment_82.fsb
fireball4 - segment_83.fsb
hurt1 - segment_84.fsb
hurt2 - segment_85.fsb
plop - segment_86.fsb
say1 - segment_87.fsb
say2 - segment_88.fsb
say3 - segment_89.fsb
step1 - segment_90.fsb
step2 - segment_91.fsb
hurt1 - segment_92.fsb
hurt2 - segment_93.fsb
hurt3 - segment_94.fsb
say1 - segment_95.fsb
say2 - segment_96.fsb
say3 - segment_97.fsb
step1 - segment_98.fsb
step2 - segment_99.fsb
step3 - segment_100.fsb
milk1 - segment_101.fsb
death - segment_102.fsb
say1 - segment_103.fsb
say2 - segment_104.fsb
say3 - segment_105.fsb
death - segment_106.fsb
hit1 - segment_107.fsb
hit2 - segment_108.fsb
hit3 - segment_109.fsb
idle1 - segment_110.fsb
idle2 - segment_111.fsb
idle3 - segment_112.fsb
portal - segment_113.fsb
portal2 - segment_114.fsb
scream1 - segment_115.fsb
scream2 - segment_116.fsb
scream3 - segment_117.fsb
stare - segment_118.fsb
hit1 - segment_119.fsb
hit2 - segment_120.fsb
wings1 - segment_121.fsb
wings3 - segment_122.fsb
wings5 - segment_123.fsb
growl2 - segment_124.fsb
growl3 - segment_125.fsb
affectionate_scream - segment_126.fsb
charge - segment_127.fsb
death - segment_128.fsb
moan1 - segment_129.fsb
moan2 - segment_130.fsb
moan3 - segment_131.fsb
scream1 - segment_132.fsb
scream2 - segment_133.fsb
scream3 - segment_134.fsb
ambient1 - segment_135.fsb
attack_loop - segment_136.fsb
curse - segment_137.fsb
elder_death - segment_138.fsb
elder_hit1 - segment_139.fsb
elder_idle3 - segment_140.fsb
flop1 - segment_141.fsb
guardian_death - segment_142.fsb
NULL_0 - segment_143.fsb
land_death - segment_144.fsb
land_hit1 - segment_145.fsb
land_idle1 - segment_146.fsb
angry1 - segment_147.fsb
death1 - segment_148.fsb
death2 - segment_149.fsb
idle1 - segment_150.fsb
idle2 - segment_151.fsb
idle3 - segment_152.fsb
idle4 - segment_153.fsb
idle5 - segment_154.fsb
spit1 - segment_155.fsb
spit2 - segment_156.fsb
hurt1 - segment_157.fsb
hurt2 - segment_158.fsb
hurt3 - segment_159.fsb
eat1 - segment_160.fsb
eat2 - segment_161.fsb
eat3 - segment_162.fsb
step1 - segment_163.fsb
step2 - segment_164.fsb
step3 - segment_165.fsb
step4 - segment_166.fsb
step5 - segment_167.fsb
swag - segment_168.fsb
angry1 - segment_169.fsb
armor - segment_170.fsb
breathe1 - segment_171.fsb
breathe2 - segment_172.fsb
breathe3 - segment_173.fsb
death - segment_174.fsb
angry1 - segment_175.fsb
angry2 - segment_176.fsb
death - segment_177.fsb
hit1 - segment_178.fsb
hit2 - segment_179.fsb
hit3 - segment_180.fsb
idle1 - segment_181.fsb
idle2 - segment_182.fsb
idle3 - segment_183.fsb
eat1 - segment_184.fsb
eat2 - segment_185.fsb
eat3 - segment_186.fsb
gallop1 - segment_187.fsb
gallop2 - segment_188.fsb
gallop3 - segment_189.fsb
hit1 - segment_190.fsb
hit2 - segment_191.fsb
hit3 - segment_192.fsb
idle1 - segment_193.fsb
idle2 - segment_194.fsb
idle3 - segment_195.fsb
jump - segment_196.fsb
land - segment_197.fsb
leather - segment_198.fsb
death - segment_199.fsb
hit1 - segment_200.fsb
hit2 - segment_201.fsb
hit3 - segment_202.fsb
idle1 - segment_203.fsb
idle2 - segment_204.fsb
idle3 - segment_205.fsb
soft1 - segment_206.fsb
soft2 - segment_207.fsb
soft3 - segment_208.fsb
wood1 - segment_209.fsb
wood2 - segment_210.fsb
wood3 - segment_211.fsb
death - segment_212.fsb
hit1 - segment_213.fsb
hit2 - segment_214.fsb
hit3 - segment_215.fsb
idle1 - segment_216.fsb
idle2 - segment_217.fsb
idle3 - segment_218.fsb
idle2 - segment_219.fsb
death1 - segment_220.fsb
hurt2 - segment_221.fsb
step4 - segment_222.fsb
throw - segment_223.fsb
death - segment_224.fsb
hit1 - segment_225.fsb
hit2 - segment_226.fsb
hit3 - segment_227.fsb
walk1 - segment_228.fsb
walk2 - segment_229.fsb
walk3 - segment_230.fsb
ambient1 - segment_231.fsb
ambient2 - segment_232.fsb
ambient5 - segment_233.fsb
close1 - segment_234.fsb
close3 - segment_235.fsb
death1 - segment_236.fsb
death2 - segment_237.fsb
hurt_close1 - segment_238.fsb
hurt_close2 - segment_239.fsb
hurt1 - segment_240.fsb
hurt2 - segment_241.fsb
hurt3 - segment_242.fsb
open2 - segment_243.fsb
open3 - segment_244.fsb
shoot1 - segment_245.fsb
shoot4 - segment_246.fsb
hit1 - segment_247.fsb
hit2 - segment_248.fsb
hit3 - segment_249.fsb
big1 - segment_250.fsb
big2 - segment_251.fsb
big3 - segment_252.fsb
jump1 - segment_253.fsb
jump2 - segment_254.fsb
jump3 - segment_255.fsb
small1 - segment_256.fsb
small2 - segment_257.fsb
small3 - segment_258.fsb
death - segment_259.fsb
pig_boost - segment_260.fsb
pig_boost - segment_261.fsb
pig_boost - segment_262.fsb
say1 - segment_263.fsb
say2 - segment_264.fsb
say3 - segment_265.fsb
step1 - segment_266.fsb
step2 - segment_267.fsb
step3 - segment_268.fsb
hurt1 - segment_269.fsb
hurt2 - segment_270.fsb
hurt3 - segment_271.fsb
idle1 - segment_272.fsb
idle2 - segment_273.fsb
idle3 - segment_274.fsb
hop1 - segment_275.fsb
hop2 - segment_276.fsb
hop3 - segment_277.fsb
bunnymurder - segment_278.fsb
say1 - segment_279.fsb
say2 - segment_280.fsb
say3 - segment_281.fsb
shear - segment_282.fsb
step1 - segment_283.fsb
step2 - segment_284.fsb
step3 - segment_285.fsb
NULL_1 - segment_286.fsb
hit2 - segment_287.fsb
hit3 - segment_288.fsb
kill - segment_289.fsb
say1 - segment_290.fsb
say2 - segment_291.fsb
say3 - segment_292.fsb
step1 - segment_293.fsb
step2 - segment_294.fsb
step3 - segment_295.fsb
death - segment_296.fsb
hurt1 - segment_297.fsb
hurt2 - segment_298.fsb
hurt3 - segment_299.fsb
say1 - segment_300.fsb
say2 - segment_301.fsb
say3 - segment_302.fsb
step1 - segment_303.fsb
step2 - segment_304.fsb
step3 - segment_305.fsb
big1 - segment_306.fsb
big2 - segment_307.fsb
big3 - segment_308.fsb
small1 - segment_309.fsb
small2 - segment_310.fsb
small3 - segment_311.fsb
attack1 - segment_312.fsb
attack2 - segment_313.fsb
death1 - segment_314.fsb
death2 - segment_315.fsb
death3 - segment_316.fsb
hurt1 - segment_317.fsb
hurt2 - segment_318.fsb
hurt3 - segment_319.fsb
bow - segment_320.fsb
death - segment_321.fsb
say1 - segment_322.fsb
say2 - segment_323.fsb
say3 - segment_324.fsb
step1 - segment_325.fsb
step2 - segment_326.fsb
step3 - segment_327.fsb
ambient1 - segment_328.fsb
ambient2 - segment_329.fsb
death3 - segment_330.fsb
hurt1 - segment_331.fsb
hurt2 - segment_332.fsb
idle2 - segment_333.fsb
death1 - segment_334.fsb
hurt4 - segment_335.fsb
step3 - segment_336.fsb
death - segment_337.fsb
haggle1 - segment_338.fsb
haggle3 - segment_339.fsb
hit1 - segment_340.fsb
hit2 - segment_341.fsb
hit3 - segment_342.fsb
idle1 - segment_343.fsb
idle2 - segment_344.fsb
idle3 - segment_345.fsb
no1 - segment_346.fsb
no2 - segment_347.fsb
yes1 - segment_348.fsb
yes2 - segment_349.fsb
death1 - segment_350.fsb
death2 - segment_351.fsb
hurt1 - segment_352.fsb
hurt2 - segment_353.fsb
hurt3 - segment_354.fsb
idle1 - segment_355.fsb
idle2 - segment_356.fsb
idle3 - segment_357.fsb
fangs - segment_358.fsb
idle1 - segment_359.fsb
idle2 - segment_360.fsb
idle3 - segment_361.fsb
cast1 - segment_362.fsb
cast2 - segment_363.fsb
death1 - segment_364.fsb
death2 - segment_365.fsb
hurt1 - segment_366.fsb
hurt2 - segment_367.fsb
prepare_attack1 - segment_368.fsb
prepare_attack2 - segment_369.fsb
prepare_summon - segment_370.fsb
prepare_wololo - segment_371.fsb
idle1 - segment_372.fsb
idle2 - segment_373.fsb
death1 - segment_374.fsb
death2 - segment_375.fsb
hurt1 - segment_376.fsb
hurt2 - segment_377.fsb
charge1 - segment_378.fsb
charge2 - segment_379.fsb
ambient5 - segment_380.fsb
ambient1 - segment_381.fsb
ambient2 - segment_382.fsb
death1 - segment_383.fsb
death2 - segment_384.fsb
death3 - segment_385.fsb
hurt1 - segment_386.fsb
hurt2 - segment_387.fsb
hurt3 - segment_388.fsb
drink1 - segment_389.fsb
drink2 - segment_390.fsb
drink3 - segment_391.fsb
throw1 - segment_392.fsb
throw2 - segment_393.fsb
throw3 - segment_394.fsb
idle1 - segment_395.fsb
woodbreak - segment_396.fsb
death - segment_397.fsb
hurt1 - segment_398.fsb
shoot - segment_399.fsb
spawn - segment_400.fsb
bark1 - segment_401.fsb
bark2 - segment_402.fsb
bark3 - segment_403.fsb
death - segment_404.fsb
growl1 - segment_405.fsb
growl2 - segment_406.fsb
hurt1 - segment_407.fsb
hurt2 - segment_408.fsb
hurt3 - segment_409.fsb
panting - segment_410.fsb
shake - segment_411.fsb
step1 - segment_412.fsb
step2 - segment_413.fsb
step3 - segment_414.fsb
whine - segment_415.fsb
hiss1 - segment_416.fsb
hiss2 - segment_417.fsb
hitt1 - segment_418.fsb
hitt2 - segment_419.fsb
hitt3 - segment_420.fsb
meow1 - segment_421.fsb
meow2 - segment_422.fsb
meow3 - segment_423.fsb
purr1 - segment_424.fsb
purr2 - segment_425.fsb
purreow1 - segment_426.fsb
purreow2 - segment_427.fsb
idle1 - segment_428.fsb
idle4 - segment_429.fsb
idle1 - segment_430.fsb
idle2 - segment_431.fsb
step1 - segment_432.fsb
step2 - segment_433.fsb
warning1 - segment_434.fsb
warning2 - segment_435.fsb
hurt1 - segment_436.fsb
hurt2 - segment_437.fsb
death1 - segment_438.fsb
death2 - segment_439.fsb
death - segment_440.fsb
hurt1 - segment_441.fsb
hurt2 - segment_442.fsb
remedy - segment_443.fsb
unfect - segment_444.fsb
say1 - segment_445.fsb
say2 - segment_446.fsb
step1 - segment_447.fsb
step2 - segment_448.fsb
step3 - segment_449.fsb
wood1 - segment_450.fsb
wood2 - segment_451.fsb
wood3 - segment_452.fsb
zpig1 - segment_453.fsb
zpig2 - segment_454.fsb
zpig3 - segment_455.fsb
zpigangry1 - segment_456.fsb
zpigangry2 - segment_457.fsb
zpigangry3 - segment_458.fsb
zpigdeath - segment_459.fsb
zpighurt1 - segment_460.fsb
zpighurt2 - segment_461.fsb
say1 - segment_462.fsb
say2 - segment_463.fsb
say3 - segment_464.fsb
death - segment_465.fsb
hurt1 - segment_466.fsb
hurt2 - segment_467.fsb
bass - segment_468.fsb
bassattack - segment_469.fsb
bd - segment_470.fsb
harp - segment_471.fsb
hat - segment_472.fsb
pling - segment_473.fsb
snare - segment_474.fsb
portal - segment_475.fsb
anvil_break - segment_476.fsb
anvil_land - segment_477.fsb
anvil_use - segment_478.fsb
bowhit1 - segment_479.fsb
bowhit2 - segment_480.fsb
bowhit3 - segment_481.fsb
break - segment_482.fsb
burp - segment_483.fsb
chestclosed - segment_484.fsb
chestopen - segment_485.fsb
close - segment_486.fsb
open - segment_487.fsb
click - segment_488.fsb
door_close - segment_489.fsb
door_open - segment_490.fsb
drink - segment_491.fsb
eat1 - segment_492.fsb
eat2 - segment_493.fsb
eat3 - segment_494.fsb
fizz - segment_495.fsb
fuse - segment_496.fsb
glass1 - segment_497.fsb
glass2 - segment_498.fsb
glass3 - segment_499.fsb
levelup - segment_500.fsb
orb - segment_501.fsb
pop - segment_502.fsb
pop2 - segment_503.fsb
swim1 - segment_504.fsb
swim3 - segment_505.fsb
swim4 - segment_506.fsb
hurt - segment_507.fsb
toast - segment_508.fsb
use_totem - segment_509.fsb
camera1 - segment_510.fsb
camera2 - segment_511.fsb
camera3 - segment_512.fsb
ladder1 - segment_513.fsb
ladder2 - segment_514.fsb
ladder3 - segment_515.fsb
cloth1 - segment_516.fsb
cloth2 - segment_517.fsb
cloth3 - segment_518.fsb
grass1 - segment_519.fsb
grass2 - segment_520.fsb
grass3 - segment_521.fsb
gravel1 - segment_522.fsb
gravel2 - segment_523.fsb
gravel3 - segment_524.fsb
sand1 - segment_525.fsb
sand2 - segment_526.fsb
sand3 - segment_527.fsb
snow1 - segment_528.fsb
snow2 - segment_529.fsb
snow3 - segment_530.fsb
stone1 - segment_531.fsb
stone2 - segment_532.fsb
stone3 - segment_533.fsb
wood1 - segment_534.fsb
wood2 - segment_535.fsb
wood3 - segment_536.fsb
cloth1 - segment_537.fsb
cloth2 - segment_538.fsb
cloth3 - segment_539.fsb
grass1 - segment_540.fsb
grass2 - segment_541.fsb
grass3 - segment_542.fsb
gravel1 - segment_543.fsb
gravel2 - segment_544.fsb
gravel3 - segment_545.fsb
sand1 - segment_546.fsb
sand2 - segment_547.fsb
sand3 - segment_548.fsb
snow1 - segment_549.fsb
snow2 - segment_550.fsb
snow3 - segment_551.fsb
stone1 - segment_552.fsb
stone2 - segment_553.fsb
stone3 - segment_554.fsb
wood1 - segment_555.fsb
wood2 - segment_556.fsb
wood3 - segment_557.fsb
```
