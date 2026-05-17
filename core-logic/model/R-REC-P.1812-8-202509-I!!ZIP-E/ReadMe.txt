Digital maps of ?N and N0

Recommendations ITU-R P.452 and ITU-R P.1812 each require two climatological parameters:
1. The “average” annual value of ?N (N-units/km), the difference in the values of the refractivity at the surface and 1000 m above the surface.
2. The “average” sea level value of surface refractivity, N0 (N-units).

These are required for the diffraction and troposcatter sub-models respectively. “Average” is normally interpreted as “median”. In Recommendations ITU-R P.452 and ITU-R P.1812 these maps are given in paper form (originally drawn by Bean et al in 1966 based on 112 radiosonde stations from 4 months of each of 5 years). 

In accordance with Document ITU-R 3J/104 Annex 8 (2009), digital maps of median annual ?N and median annual N0 have been prepared using the methods described in Document ITU-R 3J/62 (2009) to be made available on the ITU-R/SG3 website.

The maps are contained in the files DN50.TXT and N050.TXT, respectively. The data are from 0o to 360o in longitude and from +90o to –90o in latitude, with a resolution of 1.5o in both latitude and longitude. The data are used in conjunction with the companion data files LAT.TXT and LON.TXT containing respectively the latitudes and longitudes of the corresponding entries (gridpoints) in the files DN50.TXT and N050.TXT. For a location different from the gridpoints, the parameter at the desired location can be derived by performing a bi-linear interpolation on the values at the four closest gridpoints, as described in Recommendation ITU-R P.1144.

Note that the new digital maps have been derived from a new analysis of a ten-year (1983–1992) global dataset of radiosonde ascents. The digital maps are therefore not identical to the paper maps in Recommendations ITU-R P.452 and ITU-R P.1812. As would be expected, the new and old maps agree qualitatively on the global scale, but show detailed differences on the local scale. These differences are largely attributable to the higher resolution and longer time-span of the dataset used in the new analysis. The Annex below compares the new and old maps. Where significant differences occur, the new maps generally represent the data better than the old maps.


Annex: Comparison with the existing “paper” maps

1 The Bean and EBU maps

A digitisation of the two Bean maps in Recommendations ITU-R P.452/P.1812 has been carried out by the EBU. This was not a re-analysis of the data, but an interpolation of the Bean contours to generate 0.5? gridded data. As such, the EBU digital maps have limitations, some due to the limitations of the Bean maps, and some due to the digitisation process:
1. The Bean maps only covered latitudes between 80?N and 70?S. The EBU maps have been extrapolated to include the range 83?N and 90?S.
2. The Bean map of N0 used a non-linear (and unspecified) latitude axis. The EBU digitisation dealt with this by interpolation between the values given on the scale of the latitude axis.
3. The EBU maps show a variation with longitude at latitude 90?S (a single point).
4. The EBU maps have discontinuities at ?180? longitude, although these are reasonably small.

These limitations were one reason for carrying out a new analysis of the data. However the EBU digitised versions of the Bean maps were valuable for a statistical analysis of the difference between the new and old versions of the maps.

In the following, the new maps are referred to as the “WRPM” maps. The maps were produced as part of the development in the UK of a Wide Range Propagation Model funded by Ofcom.



2 Comparisons of the WRPM and Bean/EBU maps

The WRPM and Bean maps are shown in Figure 1 to Figure 4.




Figure 1: Median annual values of ?N, N-units/km (WRPM)


Figure 2: Average annual values of ?N, N-units/km (Bean)



Figure 3: Median sea-level surface refractivity, N-units (WRPM)


Figure 4: Sea-level surface refractivity, N-units (Bean)



The ?N maps were compared qualitatively in Document ITU-R 3J/62 (2009). There are differences in detail. For example, lower values are seen on the new map in mountainous areas like the Himalayas. However, the new map actually reflects the data very well and the difference is the result of ?N being defined relative to the surface, not sea level, unlike N0 which is a sea level value. At an altitude of ~3 700 m the measured values of median ?N are ~24 N-units/km, as would be expected at this altitude. This altitude effect is not seen in the Bean map, presumably due to the lower resolution of the data.

Some statistics of the WRPM and Bean maps, and the differences between them are now given. The statistics are based on the 24 000 map values on the 1.5? ITU grid that lie within the limits of the Bean maps: latitudes 79.5?N to 69?S and longitudes 180?W to 178.5?E.

The mean, standard deviation, deciles and minimum and maximum values of (a) the WRPM map values, (b) the Bean/EBU map values, and (c) the difference in the two map values (WRPM–Bean) were calculated.

3 Statistics of ?N

Table 1: Statistics of median ?N (N-units/km)

StatisticWRPM mapBean/EBU mapWRPM–BeanMean	45.4	49.8	–4.4Std dev	8.5	8.4	4.9Decile value36.6, 57.440.0, 60.1–10.2, 1.2Extreme value24.6, 79.933.3, 80.1–45.4, 20.3
For ?N the global mean value of the WRPM maps is 4.4 N-units/km lower than on the Bean maps. The reason is not clear, but may be partly due to the lower resolution of the Bean maps and the fact that there are fewer radiosonde stations in the most mountainous parts of the world. The Bean global average value of 49.8 N-units/km does seem rather high. The “standard” 4/3 k-value corresponds to ?N = 39. The two maps have comparable standard deviations, deciles, minimum and maximum values.

Considering the statistics of the differences between the maps, the maps agree to within 5.8 N-units/km at 80% of the locations, after allowing for the shift in the mean value of 4.4 N-units/km. This is not unreasonable, being ~10% of the mean value. The extreme differences (negative and positive) are quite large (100% of the mean value of ?N!). The WRPM map gives a value of ?N that is 45.4 N-units/km lower than the Bean map at 25.5?N, 46.5?E. This is near Riyadh in Saudi Arabia which is at a height of ~600 m. The value of ?N measured at Riyadh is 26 N-units/km. About 200 km away, on the coast of the Persian Gulf, the measured values are 60 (Dahran) and 77 N-units/km (Qatar). The Bean map gives a value of 70–80 N-units/km across the whole of this region. The large difference here is clearly due to the lower resolution of the Bean map which can’t track the strong gradients in this part of the world.

The WRPM map gives a value of ?N that is 20.3 N-units higher than the Bean map at 18.0?S, 121.5?E, on the north coast of Western Australia. The new maps used 5 radiosonde stations on this coast, all of which had a value of median ?N ? 60 N-units/km. The co-ordinates are very close to the radiosonde station at Broome, which has ?N = 72.1 N-units/km. The Bean value here is ~50  N-units/km. Again, the large difference reflects a difference between measured values and the Bean map.

In conclusion, the WRPM and Bean/EBU maps are qualitatively similar. The WRPM maps have a lower global average value, but the Bean global average appears to be rather high. At particular locations there are some large differences between the maps. Detailed investigation of the two extreme cases showed that the WRPM map agreed with local measurements, and the difference is almost certainly due to the lower resolution of the Bean map.

4 Statistics of N0

Table 2: Statistics of median N0 (N-units)

StatisticWRPM mapBean/EBU mapWRPM–BeanMean	338	336	2.3Std dev	24	23	7.1Decile values314, 376310, 370–4.3, 9.8Extreme values295, 389286, 394–43.5, 52.8
For N0 the global mean values of the WRPM and Bean maps agree very well, as do the standard deviations, deciles, minimum and maximum values.

Considering the statistics of the differences between the maps, the maps agree to within 7.5 N-units at 80% of the locations, after allowing for the shift in the mean value of 2.3 N-units. This is only ~2% of the mean value. The extreme differences (negative and positive) are also a much smaller fraction (~15%) of the mean values of these quantities compared to the ?N case. The location where the WRPM map is 43.5 N-units lower than the Bean map at 25.5?N, 46.5?E. This is the same location that gave rise to the largest difference in ?N, and the reason for the discrepancy is similar. Even the Bean map is showing quite steep gradients of N0 in this region, but these don’t quite match the more recent data.

The WRPM map gives a value of N0 that is 52.8 N-units higher than the Bean map at 18?N, 24?E, in the Eastern Sahara Desert. There were no stations in this area with sufficient high-quality ascents to be included in the new analysis. Both the WRPM and the Bean maps show a large area of “low” values over North Africa, but on the Bean map this area extends further east. In this case the hand-drawn Bean map is probably reflecting reality better than the machine-contoured WRPM map.

In conclusion, the WRPM and Bean/EBU maps generally agree very well. The largest differences between the maps amounted to ~15% of the mean value of N0. In one extreme case the WRPM map agreed with local measurements, and the difference is almost certainly due to the low resolution of the Bean map. In another extreme case, the difference is in a location (eastern Sahara) where there is a “data hole”. In this case the hand-drawn Bean map is probably closer to the truth.

6


