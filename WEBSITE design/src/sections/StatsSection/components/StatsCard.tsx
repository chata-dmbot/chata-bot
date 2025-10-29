export type StatCardProps = {
  cardVariant: string;
  label: string;
  value: string;
  layout: "label-top" | "label-bottom";
  valueVariant: string;
};

export const StatCard = (props: StatCardProps) => {
  return (
    <div
      className={`absolute box-border caret-transparent overflow-hidden ${props.cardVariant}`}
    >
      {props.layout === "label-top" ? (
        <>
          <div className="box-border caret-transparent text-black text-xs font-normal bg-white flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5">
            <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
              {props.label}
            </div>
          </div>
          <div className={`box-border caret-transparent ${props.valueVariant}`}>
            {props.value}
          </div>
        </>
      ) : (
        <>
          <div className={`box-border caret-transparent ${props.valueVariant}`}>
            {props.value}
          </div>
          <div className="box-border caret-transparent text-black text-xs font-normal bg-white flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit mb-0 px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5 md:mb-[3px]">
            <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
              {props.label}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
