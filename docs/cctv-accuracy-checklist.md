# Validate on authorised CCTV footage

The existing sample checks do not establish accuracy on real CCTV. Use this procedure before
making detection claims. Keep footage and identifying details outside Git.

1. Obtain permission for the footage and separately for any Google processing. Use aliases
   such as camera-A in reports, without addresses, identities, or private filenames.
2. Before searching, have a person watch the complete test clips and record visible events
   and time windows in a private copy of `cctv-validation-template.csv`. A sampled contact
   sheet cannot establish that an event never occurs.
3. Include positive scenes, clearly absent scenes, and ambiguous scenes: hidden garments,
   poor lighting, distant people, occlusion, similar clothing colours, and short events.
   Record jacket versus shirt explicitly. Do not infer hidden attributes.
4. Run each query once with the documented settings. Record ranking, returned window,
   visual verdict, evidence times, and provider errors. Retrying is another API request and
   needs available upload/cost approval. Keep failures in the report.
5. Independently review supported candidates and unclear/rejected windows. Record false
   supports and missed expected events separately. A correct broad clip ranking does not
   establish accurate event timing; compare returned windows with annotated intervals.
6. Report the case counts and outcomes for each condition. State which relevant windows
   were outside the first five candidates or fell between sampled frames. Keep ranking
   scores separate from accuracy; they are not calibrated probabilities.

Do not invent an accuracy percentage from the existing three queries. Agree on acceptance
criteria with the project owner before claiming the system is ready for its intended use.
No automatic alerts or decisions about people are justified by the current sample checks.
